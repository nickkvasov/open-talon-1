import pytest
import time
import os
import psycopg
import redis
import hvac
import uuid
import subprocess
from confluent_kafka import Producer, Consumer

COMPOSE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../infrastructure'))

@pytest.fixture(scope="session")
def infrastructure():
    print(f"Starting docker-compose from {COMPOSE_PATH}")
    subprocess.run(["docker", "compose", "up", "-d", "--wait"], cwd=COMPOSE_PATH, check=True)
    print("docker-compose up complete. Waiting for services to fully initialize...")
    
    # Wait for Postgres
    wait_for_service(
        lambda: psycopg.connect("host=localhost port=5432 user=admin password=password dbname=app_db"), 
        "Postgres"
    )
    
    # Wait for Valkey
    wait_for_service(
        lambda: redis.Redis(host='localhost', port=6379, db=0).ping(),
        "Valkey"
    )
    
    # Wait for OpenBao
    def check_bao():
        client = hvac.Client(url='http://localhost:8200', token='root')
        return client.is_authenticated()
    wait_for_service(check_bao, "OpenBao")

    # Wait for Kafka
    def check_kafka():
        p = Producer({'bootstrap.servers': 'localhost:9092'})
        p.list_topics(timeout=5)
        return True
        
    wait_for_service(check_kafka, "Kafka")
    
    # Wait for Ollama and models
    def check_ollama_and_models():
        import json
        import urllib.request
        try:
            req = urllib.request.Request('http://localhost:11434/api/tags')
            with urllib.request.urlopen(req) as response:
                if response.status != 200: return False
                data = json.loads(response.read().decode())
                models = [m['name'] for m in data.get('models', [])]
                has_gemma4_31b = any(m.startswith('gemma4:31b') for m in models)
                has_gemma4_e4b = any(m.startswith('gemma4:e4b') or m == 'gemma4:latest' for m in models)
                return has_gemma4_31b and has_gemma4_e4b
        except Exception:
            return False
            
    # Polling up to 25 minutes to allow multi-GB models to download on slow connections
    wait_for_service(check_ollama_and_models, "Ollama Models Download", max_retries=150, sleep_seconds=10)
    
    yield
    
    print("Tearing down infrastructure...")
    subprocess.run(["docker", "compose", "down", "-v"], cwd=COMPOSE_PATH, check=True)

def wait_for_service(connect_func, name, max_retries=60, sleep_seconds=2):
    for i in range(max_retries):
        try:
            result = connect_func()
            if result is not False: # some functions return None on success
                return
        except Exception:
            pass
        time.sleep(sleep_seconds)
    raise Exception(f"Service {name} failed to become ready after {max_retries * sleep_seconds}s")

def test_postgres_and_pgvector(infrastructure):
    """Test Postgres connection and pgvector extension."""
    with psycopg.connect("host=localhost port=5432 user=admin password=password dbname=app_db") as conn:
        with conn.cursor() as cur:
            # Check if pgvector is available
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
            assert cur.fetchone()[0] == 'vector'

def test_valkey_connection(infrastructure):
    """Test Valkey set and get operations."""
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.set('test_key', 'test_value')
    assert r.get('test_key') == 'test_value'

def test_openbao_connection(infrastructure):
    """Test OpenBao secret write and read."""
    client = hvac.Client(url='http://localhost:8200', token='root')
    assert client.is_authenticated()
    
    # In OpenBao dev mode, the 'secret' KV v2 engine is enabled by default
    client.secrets.kv.v2.create_or_update_secret(
        path='test_secret',
        secret=dict(foo='bar'),
        mount_point='secret'
    )
    
    response = client.secrets.kv.v2.read_secret_version(
        path='test_secret',
        mount_point='secret'
    )
    assert response['data']['data']['foo'] == 'bar'

def test_kafka_connection(infrastructure):
    """Test Kafka producer and consumer."""
    from confluent_kafka.admin import AdminClient, NewTopic
    from confluent_kafka import TopicPartition
    
    topic = f'test-topic-{uuid.uuid4()}'
    
    # Ensure topic exists
    admin = AdminClient({'bootstrap.servers': '127.0.0.1:9092'})
    fs = admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
    for topic_name, f in fs.items():
        try:
            f.result()
        except Exception:
            pass
            
    # Produce message
    producer = Producer({'bootstrap.servers': '127.0.0.1:9092'})
    producer.produce(topic, key='key', value='test_message')
    producer.flush()
    
    # Consume message via explicit assignment (bypasses consumer group join delay)
    consumer = Consumer({
        'bootstrap.servers': '127.0.0.1:9092',
        'group.id': f'test-group-{uuid.uuid4()}',
        'auto.offset.reset': 'earliest'
    })
    from confluent_kafka import TopicPartition, OFFSET_BEGINNING
    consumer.assign([TopicPartition(topic, 0, OFFSET_BEGINNING)])
    
    msg = None
    for _ in range(15):
        msg = consumer.poll(1.0)
        if msg is not None and not msg.error():
            break
            
    assert msg is not None, "Failed to consume message from Kafka"
    assert msg.value().decode('utf-8') == 'test_message'
    consumer.close()

def test_functional_pgvector_similarity_search(infrastructure):
    """Test inserting vectors and performing a similarity search."""
    with psycopg.connect("host=127.0.0.1 port=5432 user=admin password=password dbname=app_db", autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("DROP TABLE IF EXISTS items;")
            cur.execute("CREATE TABLE items (id bigserial PRIMARY KEY, embedding vector(3));")
            
            vectors = ['[1, 0, 0]', '[0, 1, 0]', '[0, 0, 1]']
            for v in vectors:
                cur.execute("INSERT INTO items (embedding) VALUES (%s::vector)", (v,))
            
            query_vector = '[1, 0.1, 0]'
            cur.execute("SELECT embedding::text FROM items ORDER BY embedding <-> %s::vector LIMIT 1;", (query_vector,))
            assert cur.fetchone()[0] == '[1,0,0]'

def test_functional_valkey_hash_and_ttl(infrastructure):
    """Test Valkey hash operations and TTL expirations."""
    r = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)
    r.hset("user:1000", mapping={"name": "Alice", "status": "active"})
    assert r.hget("user:1000", "name") == "Alice"
    assert r.hgetall("user:1000") == {"name": "Alice", "status": "active"}
    
    r.set("temp_key", "temp_value", ex=1)
    assert r.get("temp_key") == "temp_value"
    time.sleep(1.5)
    assert r.get("temp_key") is None

def test_functional_openbao_versioned_secrets(infrastructure):
    """Test OpenBao KV v2 engine's secret versioning capabilities."""
    client = hvac.Client(url='http://127.0.0.1:8200', token='root')
    
    client.secrets.kv.v2.create_or_update_secret(
        path='config_secret',
        secret={'version': '1', 'data': 'old'},
        mount_point='secret'
    )
    
    client.secrets.kv.v2.create_or_update_secret(
        path='config_secret',
        secret={'version': '2', 'data': 'new'},
        mount_point='secret'
    )
    
    latest = client.secrets.kv.v2.read_secret_version(path='config_secret', mount_point='secret')
    assert latest['data']['data']['version'] == '2'
    
    v1 = client.secrets.kv.v2.read_secret_version(path='config_secret', version=1, mount_point='secret')
    assert v1['data']['data']['version'] == '1'

def test_functional_kafka_json_payloads(infrastructure):
    """Test Kafka handling structured JSON payloads natively."""
    from confluent_kafka.admin import AdminClient, NewTopic
    from confluent_kafka import TopicPartition, OFFSET_BEGINNING
    import json
    
    topic = f'json-topic-{uuid.uuid4()}'
    
    admin = AdminClient({'bootstrap.servers': '127.0.0.1:9092'})
    fs = admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
    for topic_name, f in fs.items():
        try: f.result()
        except: pass
        
    producer = Producer({'bootstrap.servers': '127.0.0.1:9092'})
    payload = {"event_type": "user_signup", "user_id": 12345}
    producer.produce(topic, key='user_12345', value=json.dumps(payload))
    producer.flush()
    
    consumer = Consumer({
        'bootstrap.servers': '127.0.0.1:9092',
        'group.id': f'test-group-{uuid.uuid4()}',
        'auto.offset.reset': 'earliest'
    })
    
    consumer.assign([TopicPartition(topic, 0, OFFSET_BEGINNING)])
    
    received_payload = None
    for _ in range(15):
        msg = consumer.poll(1.0)
        if msg is not None and not msg.error():
            received_payload = json.loads(msg.value().decode('utf-8'))
            break
            
    assert received_payload is not None
    assert received_payload["event_type"] == "user_signup"
    assert received_payload["user_id"] == 12345
    consumer.close()

def test_functional_ollama_serving(infrastructure):
    """Test Ollama serving specific language models."""
    import urllib.request
    import json
    
    # Check if models are available (we know they are from wait hook, but test explicitly)
    req = urllib.request.Request('http://127.0.0.1:11434/api/tags')
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        models = [m['name'] for m in data['models']]
        assert any(m.startswith('gemma4:31b') for m in models)
        assert any(m.startswith('gemma4:e4b') or m == 'gemma4:latest' for m in models)
        
    # Perform basic inference generation for both models
    for model_name in ["gemma4:latest", "gemma4:31b"]:
        payload = json.dumps({
            "model": model_name,
            "prompt": "Reply with precisely the word: hello",
            "stream": False
        }).encode('utf-8')
        req = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=payload, headers={'Content-Type': 'application/json'})
        # Timeout is set high (120s) because loading large 9B models into memory on first run takes significant time
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode())
            assert 'response' in result
            assert len(result['response']) > 0
