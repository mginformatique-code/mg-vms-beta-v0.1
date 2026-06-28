# MG-VMS — Image (ANPR AI) Testing

Endpoint: POST /api/ai/analyze-plate  (multipart form field `file`), requires role >= client.
Uses emergentintegrations LlmChat (openai gpt-5.4) with EMERGENT_LLM_KEY.

## Rules
- Use base64/real JPEG or PNG images containing a vehicle/plate. No blank/solid images.
- Accepted: JPEG, PNG, WEBP only. Max 8MB.
- Returns JSON: {plate, country, vehicle_color, vehicle_make, vehicle_model, vehicle_type, confidence}
- On success a plate record is also stored and visible in /api/plates.

## Example
```
curl -X POST $URL/api/ai/analyze-plate -H "Authorization: Bearer $TOKEN" -F "file=@car.jpg"
```
