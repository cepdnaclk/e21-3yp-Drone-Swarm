const express = require("express");
const Project = require("../../models/Projects");
const { authenticateJWT } = require("../../middleware/auth");

const router = express.Router();

function joinUrl(baseUrl, path) {
    const base = String(baseUrl || "").replace(/\/+$/, "");
    const suffix = `/${String(path || "").replace(/^\/+/, "")}`;
    return `${base}${suffix}`;
}

function safeJsonParse(text) {
    try {
        return JSON.parse(text);
    } catch (_error) {
        return null;
    }
}

router.all("/:projectSlug/*", authenticateJWT, async (req, res) => {
    try {
        const { projectSlug } = req.params;
        const passthroughPath = req.params[0] || "";

        const project = await Project.findOne({ slug: projectSlug.toLowerCase() });
        if (!project) {
            return res.status(404).json({
                ok: false,
                message: "Project not found.",
            });
        }

        if (!project.service?.enabled) {
            return res.status(403).json({
                ok: false,
                message: "Service is disabled for this project.",
            });
        }

        if (!project.service?.internalBaseUrl) {
            return res.status(400).json({
                ok: false,
                message: "Project service internalBaseUrl is not configured.",
            });
        }

        const requiredScopes = Array.isArray(project.service?.requiredScopes)
            ? project.service.requiredScopes
            : [];
        const tokenScopes = Array.isArray(req.auth?.scopes) ? req.auth.scopes : [];

        const missingScope = requiredScopes.find((scope) => !tokenScopes.includes(scope));
        if (missingScope) {
            return res.status(403).json({
                ok: false,
                message: `Missing required scope: ${missingScope}`,
            });
        }

        const targetUrl = joinUrl(project.service.internalBaseUrl, passthroughPath);
        const queryString = req.originalUrl.includes("?")
            ? req.originalUrl.slice(req.originalUrl.indexOf("?"))
            : "";

        const requestHeaders = {
            accept: req.header("accept") || "application/json",
            "x-user-id": String(req.auth?.sub || ""),
            "x-user-email": String(req.auth?.email || ""),
            "x-project-slug": project.slug,
        };

        if (req.header("content-type")) {
            requestHeaders["content-type"] = req.header("content-type");
        }

        if (project.service.authMode === "service-token" && process.env.INTERNAL_SERVICE_TOKEN) {
            requestHeaders["x-internal-service-token"] = process.env.INTERNAL_SERVICE_TOKEN;
        }

        const method = String(req.method || "GET").toUpperCase();
        const fetchOptions = {
            method,
            headers: requestHeaders,
        };

        if (!["GET", "HEAD"].includes(method)) {
            fetchOptions.body = req.body ? JSON.stringify(req.body) : undefined;
        }

        const upstream = await fetch(`${targetUrl}${queryString}`, fetchOptions);
        const responseText = await upstream.text();
        const asJson = safeJsonParse(responseText);

        if (asJson !== null) {
            return res.status(upstream.status).json(asJson);
        }

        return res.status(upstream.status).send(responseText);
    } catch (error) {
        return res.status(502).json({
            ok: false,
            message: "Gateway request failed.",
            error: error.message,
        });
    }
});

module.exports = router;
