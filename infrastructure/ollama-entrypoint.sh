#!/bin/sh
# Start Ollama in the background
/bin/ollama serve &

# Wait for the Ollama API to be responsive
pid=$!
echo "Waiting for Ollama API to start..."
while ! ollama list > /dev/null 2>&1; do
  sleep 1
done

collect_models() {
  if [ -n "$(echo "$REQUIRED_MODELS" | tr -d '[:space:]')" ]; then
    configured_models="$REQUIRED_MODELS"
  else
    configured_models="$OPEN_TALON_DEFAULT_REASONING_MODEL,$RETRIEVER_DEFAULT_EMBEDDING_MODEL,$RETRIEVER_DEFAULT_VISION_MODEL"
  fi

  collected_models=""
  for model in $(echo "$configured_models" | tr ',' ' '); do
    if [ -z "$model" ]; then
      continue
    fi
    case " $collected_models " in
      *" $model "*) ;;
      *) collected_models="$collected_models $model" ;;
    esac
  done
  echo "$collected_models"
}

# Pull the desired models. REQUIRED_MODELS remains an explicit override; when
# omitted, the service pulls the model roles configured for the local system.
MODELS_TO_PULL=$(collect_models)
echo "Ollama API is ready! Pulling models:$MODELS_TO_PULL"
for model in $MODELS_TO_PULL; do
    echo "Pulling model: $model"
    ollama pull $model
done

echo "Models pulled successfully! Bringing Ollama back to the foreground..."
# Wait on the original process to keep the container running
wait $pid
