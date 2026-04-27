# Sample Local Project: Connect To Central Backend

This sample gives you:
- a small Node.js backend (`backend/server.js`)
- a simple project page (`backend/public/index.html`)
- internal endpoints that can be called through your central gateway

## 1) Start the sample service

```bash
cd swarm_web/sample_local_project/backend
cp .env.example .env
npm install
npm run start
```

By default it runs on `http://localhost:7001`.

## 2) Ensure central backend has matching internal token

Set this in central backend `.env`:

```env
INTERNAL_SERVICE_TOKEN=change_me
```

Set the same value in sample service `.env`.

## 3) Register the project in central backend

Use your central project API (admin protected):

```bash
curl -X POST http://localhost:5000/api/projects \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: <YOUR_ADMIN_SECRET>" \
  -d '{
    "name": "Sample Local Project",
    "slug": "sample-local-project",
    "description": "Demo microservice connected through central gateway.",
    "projectUrl": "http://localhost:7001",
    "status": "online",
    "service": {
      "internalBaseUrl": "http://localhost:7001",
      "healthPath": "/health",
      "enabled": true,
      "authMode": "service-token",
      "requiredScopes": ["gateway:proxy"]
    }
  }'
```

## 4) Open from central frontend

- Login to your central frontend
- Go to projects page
- Open "Sample Local Project" via `projectUrl`

## 5) Call the project backend through gateway

After login, use your JWT from central auth:

```bash
TOKEN=<YOUR_JWT_TOKEN>

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/gateway/sample-local-project/status

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"land","payload":{"speed":"slow"}}' \
  http://localhost:5000/api/gateway/sample-local-project/commands
```

## Notes

- `/health` is public in the sample backend.
- `/status` and `/commands` require `x-internal-service-token` and should be called through central gateway.
- In production, use Docker network hostnames (not localhost) for `internalBaseUrl`.
