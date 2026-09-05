from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os, tempfile
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='layervault-test-')
from fastapi.testclient import TestClient
from app.main import app
c=TestClient(app)
assert c.get('/health').json()['ok'] is True
assert c.get('/api/stats').status_code==200
assert c.post('/api/projects',json={'name':'Test Project'}).status_code==200
assert c.post('/api/materials',json={'name':'PLA Black','material':'PLA'}).status_code==200
assert c.post('/api/printers',json={'name':'Test Printer','technology':'FDM'}).status_code==200
print('LayerVault smoke test: PASS')
