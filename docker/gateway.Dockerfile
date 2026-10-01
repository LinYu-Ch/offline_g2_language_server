# men-g2-ble-gateway, headless. Build context: ./men-g2-ble-gateway
# Extra context "support": ./docker
#
# The container does no Bluetooth itself: bleak talks to a BlueZ daemon over
# the D-Bus socket mounted at /var/run/dbus. Which BlueZ that is depends on the
# host; see docker/compose.<platform>.yml.
FROM python:3.12-slim-trixie
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=support gateway-constraints.txt /tmp/constraints.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -c /tmp/constraints.txt
COPY --from=support bt_check.py /usr/local/bin/bt_check.py
COPY . .
EXPOSE 8765
CMD ["python", "gateway_server.py", "--no-gui", "--host", "0.0.0.0", "--port", "8765"]
