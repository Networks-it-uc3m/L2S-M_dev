FROM python:latest
RUN apt-get update && apt-get install -y lshw
RUN pip install PyMySQL cryptography
COPY xml-init-pci.py /init-pci.py
CMD [ "python3", "/init-pci.py" ]
