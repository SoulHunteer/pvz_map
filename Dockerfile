# Используем официальный образ Python
FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    gnupg \
    libgl1 \
    libgtk-3-0 \
    libnss3 \
    libx11-xcb1 \
    xvfb

# Установка Chrome for Testing (новый официальный канал)
RUN CHROME_VERSION="132.0.6834.159" && \
    wget -O chrome.deb https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip && \
    apt-get install -y ./chrome.deb && \
    rm chrome.deb

# Установка ChromeDriver для Chrome for Testing
RUN CHROME_VERSION="132.0.6834.159" && \
    wget https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip && \
    unzip chromedriver-linux64.zip -d /usr/local/bin/ && \
    mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf chromedriver-linux64.zip

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Запускаем Xvfb в фоне и наш бот
CMD Xvfb :99 -screen 0 1024x768x16 & python -u pvz_map.py