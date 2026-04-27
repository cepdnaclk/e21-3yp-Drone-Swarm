const express = require("express");
const path = require("path");
const { config } = require("dotenv");

config();

const app = express();
const PORT = Number(process.env.PORT || 7001);
const INTERNAL_SERVICE_TOKEN = String(process.env.INTERNAL_SERVICE_TOKEN || "");

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

function verifyInternalToken(req, res, next) {
    if (!INTERNAL_SERVICE_TOKEN) {
        return next();
    }

    const incoming = req.header("x-internal-service-token");
    if (incoming !== INTERNAL_SERVICE_TOKEN) {
        return res.status(401).json({
            ok: false,
            message: "Unauthorized internal service request.",
        });
    }

    return next();
}

app.get("/health", (_req, res) => {
    return res.status(200).json({
        ok: true,
        service: "sample-local-project",
        status: "healthy",
    });
});

// These endpoints are designed to be called via the central gateway.
app.get("/status", verifyInternalToken, (req, res) => {
    return res.status(200).json({
        ok: true,
        project: "sample-local-project",
        user: {
            id: req.header("x-user-id") || null,
            email: req.header("x-user-email") || null,
        },
        gatewayProject: req.header("x-project-slug") || null,
        state: "online",
        activeRobots: 2,
        batteryAverage: 87,
    });
});

app.post("/commands", verifyInternalToken, (req, res) => {
    const { command, payload } = req.body || {};

    if (!command) {
        return res.status(400).json({
            ok: false,
            message: "command is required.",
        });
    }

    return res.status(200).json({
        ok: true,
        accepted: true,
        command,
        payload: payload || {},
        receivedAt: new Date().toISOString(),
    });
});

app.get("*", (_req, res) => {
    return res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(PORT, () => {
    console.log(`Sample local project backend running on port ${PORT}`);
});
