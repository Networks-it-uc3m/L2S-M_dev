FROM python:3.7
RUN pip install kopf kubernetes PyMySQL
COPY l2sm-operator.py /l2sm-operator.py
CMD kopf run --standalone /l2sm-operator.py
