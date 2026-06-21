# 1. पाइथन का ऑफिशियल स्लिम (Slim) इमेज यूज़ करें ताकि इमेज का साइज छोटा रहे और डिप्लॉयमेंट फ़ास्ट हो
FROM python:3.11-slim

# 2. आवश्यक सिस्टम टूल्स इंस्टॉल करें (C-एक्सटेंशन लाइब्रेरीज जैसे uvloop/orjson के लिए जरूरी है)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. वर्किंग डायरेक्टरी सेट करें
WORKDIR /Auto-Filter-Bot

# 4. पाइथन एन्वायरमेंट वेरिएबल्स (Environment Variables) सेट करें
# PYTHONDONTWRITEBYTECODE=1 -> कंटेनर में फालतू की .pyc फाइलें बनने से रोकता है (रैम और डिस्क स्पेस बचती है)
# PYTHONUNBUFFERED=1 -> लॉग्स को तुरंत लाइव दिखाता है, कोई बफ़रिंग नहीं होती
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 5. पहले सिर्फ requirements.txt कॉपी करें (डॉकर लेयर कैशिंग का फायदा उठाने के लिए)
COPY requirements.txt .

# 6. डिपेंडेंसीज इंस्टॉल करें और पिप (pip) का कैश साफ़ करें ताकि कंटेनर का लोड कम रहे
RUN pip install --no-cache-dir -r requirements.txt

# 7. अब प्रोजेक्ट का बाकी सारा कोड कॉपी करें
COPY . .

# 8. बोट को रन करने की कमांड
CMD ["python", "bot.py"]
