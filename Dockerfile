FROM node:22-alpine AS three_vendor
WORKDIR /vendor
RUN npm init -y >/dev/null 2>&1 && npm install three@0.185.1 manifold-3d@3.5.1

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    APP_PORT=8080
WORKDIR /app
COPY requirements.txt .
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY third_party/dragonfruit/plugins/anycubic /app/third_party/dragonfruit/plugins/anycubic
COPY third_party/dragonfruit/plugins/elegoo /app/third_party/dragonfruit/plugins/elegoo
COPY third_party/dragonfruit/plugins/athena /app/third_party/dragonfruit/plugins/athena
COPY third_party/printer-artwork/orcaslicer /app/third_party/printer-artwork/orcaslicer
RUN mkdir -p /app/app/static/vendor/addons/controls /app/app/static/vendor/addons/loaders /app/app/static/vendor/addons/exporters /app/app/static/vendor/addons/libs /app/app/static/vendor/addons/utils /app/app/static/vendor/manifold
COPY --from=three_vendor /vendor/node_modules/three/build/three.module.min.js /app/app/static/vendor/three.module.min.js
COPY --from=three_vendor /vendor/node_modules/three/build/three.core.min.js /app/app/static/vendor/three.core.min.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/controls/OrbitControls.js /app/app/static/vendor/addons/controls/OrbitControls.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/controls/TransformControls.js /app/app/static/vendor/addons/controls/TransformControls.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/loaders/STLLoader.js /app/app/static/vendor/addons/loaders/STLLoader.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/loaders/OBJLoader.js /app/app/static/vendor/addons/loaders/OBJLoader.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/loaders/3MFLoader.js /app/app/static/vendor/addons/loaders/3MFLoader.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/exporters/STLExporter.js /app/app/static/vendor/addons/exporters/STLExporter.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/libs/fflate.module.js /app/app/static/vendor/addons/libs/fflate.module.js
COPY --from=three_vendor /vendor/node_modules/three/examples/jsm/utils/BufferGeometryUtils.js /app/app/static/vendor/addons/utils/BufferGeometryUtils.js
COPY --from=three_vendor /vendor/node_modules/manifold-3d/manifold.js /app/app/static/vendor/manifold/manifold.js
COPY --from=three_vendor /vendor/node_modules/manifold-3d/manifold.wasm /app/app/static/vendor/manifold/manifold.wasm
RUN mkdir -p /data/files /data/import /data/backups /data/thumbnails /data/print-results /data/custom-images /data/catalog-cache
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8080} --proxy-headers"]
