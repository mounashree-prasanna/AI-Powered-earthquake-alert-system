from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, lower, split, explode, trim, count, collect_list, expr, row_number
)
from pyspark.sql.window import Window
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from email.message import EmailMessage
import smtplib
import textwrap
import pandas as pd

def run_alert_pipeline():
    # Step 0: Start Spark session
    spark = SparkSession.builder.getOrCreate()

    # Step 1: Load enriched news data
    df2 = spark.read.option("header", "true").option("mode", "DROPMALFORMED").csv("earthquake_news_enriched.csv")

    df2_cleaned = df2.filter(
        col("Impact_Severity_Bucket").isNotNull() &
        col("Impact_Keywords_Str").isNotNull()
    )

    df2_keywords = df2_cleaned.withColumn(
        "keyword", explode(split(lower(col("Impact_Keywords_Str")), ","))
    ).withColumn("keyword", trim(col("keyword")))

    keyword_counts = df2_keywords.groupBy("Impact_Severity_Bucket", "keyword") \
        .agg(count("*").alias("keyword_count"))

    window_spec = Window.partitionBy("Impact_Severity_Bucket").orderBy(col("keyword_count").desc())

    top_keywords = keyword_counts.withColumn("rank", row_number().over(window_spec)) \
        .filter(col("rank") <= 10) \
        .groupBy("Impact_Severity_Bucket") \
        .agg(collect_list("keyword").alias("Top_Keywords"))

    sentiment_dist = df2_cleaned.groupBy("Impact_Severity_Bucket", "Sentiment_Label") \
        .agg(count("*").alias("count"))

    total_per_bucket = df2_cleaned.groupBy("Impact_Severity_Bucket") \
        .agg(count("*").alias("total_articles"))

    sentiment_dist_pct = sentiment_dist.join(total_per_bucket, on="Impact_Severity_Bucket") \
        .withColumn("sentiment_pct", expr("round(count / total_articles, 3)")) \
        .groupBy("Impact_Severity_Bucket") \
        .agg(
            collect_list(
                expr("concat(Sentiment_Label, ': ', sentiment_pct)")
            ).alias("Sentiment_Distribution")
        )

    impact_summary_top10_df = top_keywords.join(sentiment_dist_pct, on="Impact_Severity_Bucket") \
        .join(total_per_bucket, on="Impact_Severity_Bucket")

    # Step 2: Load seismic prediction
    df1_spark = spark.read.option("header", True).csv("predicted_earthquakes_with_impact.csv")
    latest_event_row = df1_spark.orderBy(col("time").desc()).limit(1).collect()[0]

    predicted_mag = float(latest_event_row["predicted_mag"])
    impact_level = latest_event_row["impact_level"]
    latitude = float(latest_event_row["latitude"])
    longitude = float(latest_event_row["longitude"])

    # Step 3: Convert reference table to dict
    reference_pd = impact_summary_top10_df.toPandas()

    # Fix: convert strings to dict/list
    reference_pd["Top_Keywords"] = reference_pd["Top_Keywords"].apply(
        lambda x: eval(x) if isinstance(x, str) else x
    )

    def parse_sentiment(s):
        try:
            return {i.split(":")[0].strip(): float(i.split(":")[1]) for i in s} if isinstance(s, list) else {}
        except:
            return {}
    reference_pd["Sentiment_Distribution"] = reference_pd["Sentiment_Distribution"].apply(parse_sentiment)

    reference_dict = reference_pd.set_index("Impact_Severity_Bucket").T.to_dict()

    # Step 4: Reverse geocoding
    def reverse_geocode(lat, lon):
        geolocator = Nominatim(user_agent="earthquake-alert-system")
        try:
            location = geolocator.reverse((lat, lon), timeout=10)
            if location and location.address:
                return location.address
            else:
                return "Open ocean region (no nearby land)"
        except GeocoderTimedOut:
            return "Geocoding timed out"

    location_name = reverse_geocode(latitude, longitude)

    # Step 5: Generate alert message
    def generate_earthquake_alert(impact_level, predicted_mag, latitude, longitude, location_name, ref_dict):
        if impact_level not in ref_dict:
            return f"No reference data available for impact level: {impact_level}"

        row = ref_dict[impact_level]
        keywords = row["Top_Keywords"]
        sentiments = row["Sentiment_Distribution"]
        article_count = row["total_articles"]

        neutral = sentiments.get("Neutral", 0)
        negative = sentiments.get("Negative", 0)
        positive = sentiments.get("Positive", 0)

        neutral_pct = round(neutral * 100, 1)
        negative_pct = round(negative * 100, 1)
        positive_pct = round(positive * 100, 1)

        sentiment_str = f"Neutral: {neutral_pct}%, Negative: {negative_pct}%, Positive: {positive_pct}%"
        keyword_str = ", ".join(keywords[:10])
        key1, key2, key3 = keywords[0], keywords[1], keywords[2]

        if negative_pct > 60:
            sentiment_msg = f"Around {negative_pct}% of the sentiment in related articles showed negative emotion, indicating serious concern in past similar events."
        elif negative_pct > 40:
            sentiment_msg = f"Approximately {negative_pct}% of articles reflected negative sentiment — a moderate level of public concern."
        elif negative_pct > 25:
            sentiment_msg = f"Only about {negative_pct}% of the historical sentiment was negative. This is generally not a cause for major alarm."
        else:
            sentiment_msg = f"Less than {negative_pct}% of the sentiment was negative, suggesting that public response was calm in similar cases."

        location_lower = location_name.lower()
        ocean_keywords = ["ocean", "sea", "trench", "open water", "open ocean", "gulf"]
        is_oceanic = any(word in location_lower for word in ocean_keywords)

        if is_oceanic:
            advisory = (
                f"This earthquake occurred in the ocean region ({location_name}). "
                f"While similar earthquakes on land have shown sentiment patterns like: {sentiment_msg.lower()} "
                f"and often involved impacts like {key1}, {key2}, and {key3}, there is currently no land nearby. "
                f"As a result, this event is not considered a cause for public concern."
            )
        else:
            level = impact_level.lower()
            if level == "minor":
                advisory = (
                    f"{sentiment_msg} Minor tremors like these were typically linked to terms like {key1} and {key2}. "
                    f"No action is required — just stay informed."
                )
            elif level == "light":
                advisory = (
                    f"{sentiment_msg} Light earthquakes have historically been associated with {key1} and {key2}. "
                    f"No structural damage expected — stay aware."
                )
            elif level == "moderate":
                advisory = (
                    f"{sentiment_msg} Events of moderate severity often involve {key1}, {key2}, or {key3}. "
                    f"Monitor updates and ensure surroundings are safe."
                )
            elif level == "strong":
                advisory = (
                    f"{sentiment_msg} Strong earthquakes like this have previously included impacts such as {key1}, {key2}, and {key3}. "
                    f"Take shelter and prepare for aftershocks."
                )
            elif level == "major":
                advisory = (
                    f"{sentiment_msg} Major earthquakes are commonly associated with {key1}, {key2}, and {key3}. "
                    f"Follow emergency procedures and official alerts without delay."
                )
            else:
                advisory = f"{sentiment_msg} Stay alert and follow emergency protocols if applicable."

        alert_msg = (
            f" Earthquake Alert: **{impact_level} Severity** (Predicted Magnitude: {predicted_mag})\n"
            f" Location: Latitude {latitude}, Longitude {longitude} ({location_name})\n"
            f" Based on {article_count} historical news articles, such earthquakes were often associated with:\n"
            f" Common impacts: {keyword_str}\n"
            f" Sentiment response: {sentiment_str}\n"
            f"{advisory}"
        )
        return alert_msg

    alert_message = generate_earthquake_alert(
        impact_level, predicted_mag, latitude, longitude, location_name, reference_dict
    )

    # Step 6: Print in terminal (optional)
    print("\n📢 EARTHQUAKE ALERT MESSAGE:\n")
    for paragraph in alert_message.split("\n"):
        print(textwrap.fill(paragraph, width=100))

    # Step 7: Send email
    def send_email_alert(subject, body, to_email, from_email, app_password):
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        msg.set_content(body)

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(from_email, app_password)
                smtp.send_message(msg)
            print("Alert email sent successfully.")
        except Exception as e:
            print(f"Failed to send email: {e}")

    subject = f"Earthquake Alert: {impact_level} Severity"
    wrapped_alert = "\n".join([textwrap.fill(p, width=100) for p in alert_message.split("\n")])

    # Replace these with your credentials
    to_email = "chetana.1js17cs029@gmail.com"
    from_email = "chetana.muralidharan.24@gmail.com"
    app_password = "gsdokgwxycdrfsfd"

    send_email_alert(subject, wrapped_alert, to_email, from_email, app_password)

    return alert_message

# Optional: Run directly
if __name__ == "__main__":
    run_alert_pipeline()
