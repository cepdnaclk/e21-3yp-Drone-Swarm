const express = require("express");
const mongoose = require("mongoose");
const Project = require("../../models/Projects");
const { authenticateJWT, requireAdminAccess } = require("../../middleware/auth");

const router = express.Router();

router.get("/", authenticateJWT, async (_req, res) => {
    try {
        const projects = await Project.find()
            .sort({ createdAt: -1 })
            .populate("lead", "name email phone");

        return res.status(200).json({
            ok: true,
            count: projects.length,
            projects,
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to fetch projects.",
            error: error.message,
        });
    }
});

router.post("/", requireAdminAccess, async (req, res) => {
    try {
        const {
            name,
            slug,
            description,
            projectUrl,
            status,
            lead,
            lastActiveAt,
            service,
        } = req.body;

        if (!name || !slug || !lead) {
            return res.status(400).json({
                ok: false,
                message: "name, slug and lead are required.",
            });
        }

        if (!mongoose.Types.ObjectId.isValid(lead)) {
            return res.status(400).json({
                ok: false,
                message: "Invalid lead user id.",
            });
        }

        const project = await Project.create({
            name,
            slug,
            description,
            projectUrl,
            status,
            lead,
            lastActiveAt,
            service: {
                internalBaseUrl: service?.internalBaseUrl || "",
                healthPath: service?.healthPath || "/health",
                enabled: typeof service?.enabled === "boolean" ? service.enabled : true,
                authMode: service?.authMode || "service-token",
                requiredScopes: Array.isArray(service?.requiredScopes)
                    ? service.requiredScopes
                    : [],
            },
        });

        return res.status(201).json({
            ok: true,
            message: "Project created.",
            project,
        });
    } catch (error) {
        if (error.code === 11000) {
            return res.status(409).json({
                ok: false,
                message: "Project slug already exists.",
            });
        }

        return res.status(500).json({
            ok: false,
            message: "Failed to create project.",
            error: error.message,
        });
    }
});

router.patch("/:projectId", requireAdminAccess, async (req, res) => {
    try {
        const { projectId } = req.params;

        if (!mongoose.Types.ObjectId.isValid(projectId)) {
            return res.status(400).json({
                ok: false,
                message: "Invalid project id.",
            });
        }

        const allowedFields = [
            "name",
            "slug",
            "description",
            "projectUrl",
            "status",
            "lead",
            "lastActiveAt",
            "service",
        ];

        const update = {};
        for (const field of allowedFields) {
            if (Object.prototype.hasOwnProperty.call(req.body, field)) {
                update[field] = req.body[field];
            }
        }

        if (Object.prototype.hasOwnProperty.call(update, "lead")) {
            if (!mongoose.Types.ObjectId.isValid(update.lead)) {
                return res.status(400).json({
                    ok: false,
                    message: "Invalid lead user id.",
                });
            }
        }

        if (Object.prototype.hasOwnProperty.call(update, "service")) {
            update.service = {
                internalBaseUrl: update.service?.internalBaseUrl || "",
                healthPath: update.service?.healthPath || "/health",
                enabled:
                    typeof update.service?.enabled === "boolean"
                        ? update.service.enabled
                        : true,
                authMode: update.service?.authMode || "service-token",
                requiredScopes: Array.isArray(update.service?.requiredScopes)
                    ? update.service.requiredScopes
                    : [],
            };
        }

        const project = await Project.findByIdAndUpdate(projectId, update, {
            new: true,
            runValidators: true,
        }).populate("lead", "name email phone");

        if (!project) {
            return res.status(404).json({
                ok: false,
                message: "Project not found.",
            });
        }

        return res.status(200).json({
            ok: true,
            message: "Project updated.",
            project,
        });
    } catch (error) {
        if (error.code === 11000) {
            return res.status(409).json({
                ok: false,
                message: "Project slug already exists.",
            });
        }

        return res.status(500).json({
            ok: false,
            message: "Failed to update project.",
            error: error.message,
        });
    }
});

module.exports = router;
