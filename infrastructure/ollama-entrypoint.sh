#!/bin/sh
# Start Ollama in the background
/bin/ollama serve &

# Wait for the Ollama API to be responsive
pid=$!
echo "Waiting for Ollama API to start..."
while ! ollama list > /dev/null 2>&1; do
  sleep 1
done

# Pull the desired models
echo "Ollama API is ready! Pulling models..."
ollama pull gemma4:31b
ollama pull gemma4:e4b

echo "Models pulled successfully! Bringing Ollama back to the foreground..."
# Wait on the original process to keep the container running
wait $pid
