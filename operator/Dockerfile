FROM python:latest
RUN pip install kopf kubernetes PyMySQL cryptography
COPY l2sm-operator.py /l2sm-operator.py
CMD kopf run --standalone --all-namespaces /l2sm-operator.py
