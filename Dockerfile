FROM python:3.11
WORKDIR  /app
COPY  aaron45.py .
EXPOSE 8000
CMD ["python3", "aaron45.py"]
