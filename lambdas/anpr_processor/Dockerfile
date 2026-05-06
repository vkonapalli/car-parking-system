FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y \
    tesseract \
    opencv \
    && dnf clean all

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY handler.py plate_detector.py ocr.py plate_validator.py __init__.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.lambda_handler"]
