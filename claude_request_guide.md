# Guide: Sending Text and Image Requests to Local Anthropic API

## Endpoint Configuration

- **Base URL**: `http://localhost:23333/api/anthropic/v1/messages`
- **Auth Header**: `x-api-key: Powered by Agent Maestro`
- **API Version**: `2023-06-01`

---

## 1. Text-Only Request

```bash
curl -X POST "http://localhost:23333/api/anthropic/v1/messages" \
  -H "Content-Type: application/json" \
  -H "x-api-key: Powered by Agent Maestro" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-opus-4.6-1m",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": "Hello, what is 2 + 2?"
      }
    ]
  }'
```

---

## 2. Image + Text Request

### Step 1: Convert image to base64

```bash
# Linux/macOS
base64 -i image.png | tr -d '\n'

# Windows (PowerShell)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("image.png"))
```

### Step 2: Send request with image

```bash
curl -X POST "http://localhost:23333/api/anthropic/v1/messages" \
  -H "Content-Type: application/json" \
  -H "x-api-key: Powered by Agent Maestro" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-opus-4.6-1m",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image",
            "source": {
              "type": "base64",
              "media_type": "image/png",
              "data": "<BASE64_STRING_HERE>"
            }
          },
          {
            "type": "text",
            "text": "What is in this image?"
          }
        ]
      }
    ]
  }'
```

---

## 3. Python Example

```python
import anthropic
import base64

# Configure client
client = anthropic.Anthropic(
    api_key="Powered by Agent Maestro",
    base_url="http://localhost:23333/api/anthropic"
)

# Text-only request
response = client.messages.create(
    model="claude-opus-4.6-1m",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)
print(response.content[0].text)

# Image + text request
with open("image.png", "rb") as f:
    image_data = base64.standard_b64encode(f.read()).decode("utf-8")

response = client.messages.create(
    model="claude-opus-4.6-1m",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data
                    }
                },
                {"type": "text", "text": "Describe this image."}
            ]
        }
    ]
)
print(response.content[0].text)
```

---

## Available Models

| Model | Description |
|-------|-------------|
| `claude-opus-4.6-1m` | 1M context window |
| `claude-opus-4.6-fast` | Faster variant |
| `claude-opus-4.6` | Standard |

---

## Supported Image Formats

- `image/png`
- `image/jpeg`
- `image/gif`
- `image/webp`
