# 🌍 AI-Powered Earthquake Alert System

An end-to-end system that predicts earthquake magnitudes in real time using machine learning and enriches alerts with contextual impact insights from news sentiment analysis. Built using Apache Spark, PySpark, VADER NLP, and Flask.

## 🚀 Project Overview

Earthquakes are unpredictable and can cause massive human and economic losses. Traditional alert systems often react too late and lack predictive insight. This project aims to build a real-time earthquake alert system that:

- Predicts earthquake magnitude using a **Random Forest regression model** trained on USGS data.
- Enriches alerts with **news sentiment and impact keywords** using **VADER NLP**.
- Allows human-in-the-loop alerting via a **Flask-based UI** with a “Send Alert” button.
- Sends out alert emails using the **Gmail API**.

  
## 📬 Sample Output

- Predicted Magnitude: **4.9**
- Impact Level: **Moderate**
- Keywords: *“collapse”, “rescue”, “evacuation”*
- Sentiment: *Negative*
- Sample Alert Email:  
  *"⚠️ Earthquake Alert: Strong severity predicted in Region X. Based on past events, common impacts include collapsed buildings and emergency response. Stay alert."*

---
