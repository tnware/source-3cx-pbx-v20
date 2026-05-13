FROM airbyte/python-connector-base:2.0.0

WORKDIR /airbyte/integration_code

# Copy the connector package
COPY . ./

# Install the connector and its dependencies
RUN pip install --no-cache-dir .

# AIRBYTE_ENTRYPOINT is required by the Airbyte v2 workload runner
ENV AIRBYTE_ENTRYPOINT="python -m source_3cx_xapi"

ENTRYPOINT ["python", "-m", "source_3cx_xapi"]
