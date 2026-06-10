const express = require("express");
const mongoose = require("mongoose");
const User = require("../../models/User");
const Project = require("../../models/Projects");
const { requireAdminAccess } = require("../../middleware/auth");

const router = express.Router();

router.use(requireAdminAccess);

/* ============================================================
 *  STATS
 * ============================================================ */
router.get("/stats", async (_req, res) => {
    try {
        const [userTotal, userVerified, projectAgg] = await Promise.all([
            User.countDocuments({}),
            User.countDocuments({ isVerified: true }),
            Project.aggregate([
                { $group: { _id: "$status", count: { $sum: 1 } } },
            ]),
        ]);

        const projectCounts = projectAgg.reduce(
            (acc, row) => {
                acc[row._id || "offline"] = row.count;
                acc.total += row.count;
                return acc;
            },
            { total: 0, active: 0, online: 0, maintenance: 0, offline: 0 }
        );

        return res.status(200).json({
            ok: true,
            stats: {
                users: {
                    total: userTotal,
                    verified: userVerified,
                    pending: userTotal - userVerified,
                },
                projects: projectCounts,
            },
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to load stats.",
            error: error.message,
        });
    }
});

/* ============================================================
 *  USERS
 * ============================================================ */
router.get("/users", async (req, res) => {
    try {
        const { status, q } = req.query;
        const filter = {};

        if (status === "pending") filter.isVerified = false;
        if (status === "verified") filter.isVerified = true;

        if (q) {
            const term = String(q).trim();
            if (term) {
                const safe = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
                filter.$or = [
                    { name: { $regex: safe, $options: "i" } },
                    { email: { $regex: safe, $options: "i" } },
                    { phone: { $regex: safe, $options: "i" } },
                ];
            }
        }

        const users = await User.find(filter)
            .select("-password")
            .sort({ createdAt: -1 });

        return res.status(200).json({
            ok: true,
            count: users.length,
            users,
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to load users.",
            error: error.message,
        });
    }
});

router.get("/users/:id", async (req, res) => {
    try {
        const { id } = req.params;

        if (!mongoose.Types.ObjectId.isValid(id)) {
            return res.status(400).json({ ok: false, message: "Invalid user id." });
        }

        const user = await User.findById(id).select("-password");
        if (!user) {
            return res.status(404).json({ ok: false, message: "User not found." });
        }

        return res.status(200).json({ ok: true, user });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to load user.",
            error: error.message,
        });
    }
});

router.patch("/users/:id", async (req, res) => {
    try {
        const { id } = req.params;

        if (!mongoose.Types.ObjectId.isValid(id)) {
            return res.status(400).json({ ok: false, message: "Invalid user id." });
        }

        const allowed = ["name", "phone", "isVerified"];
        const update = {};
        for (const field of allowed) {
            if (Object.prototype.hasOwnProperty.call(req.body, field)) {
                update[field] = req.body[field];
            }
        }

        const user = await User.findByIdAndUpdate(id, update, {
            new: true,
            runValidators: true,
        }).select("-password");

        if (!user) {
            return res.status(404).json({ ok: false, message: "User not found." });
        }

        return res.status(200).json({
            ok: true,
            message: "User updated.",
            user,
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to update user.",
            error: error.message,
        });
    }
});

router.delete("/users/:id", async (req, res) => {
    try {
        const { id } = req.params;

        if (!mongoose.Types.ObjectId.isValid(id)) {
            return res.status(400).json({ ok: false, message: "Invalid user id." });
        }

        if (req.auth?.sub && String(req.auth.sub) === String(id)) {
            return res.status(400).json({
                ok: false,
                message: "You cannot delete your own admin account.",
            });
        }

        const user = await User.findByIdAndDelete(id);
        if (!user) {
            return res.status(404).json({ ok: false, message: "User not found." });
        }

        return res.status(200).json({
            ok: true,
            message: "User deleted.",
            user: { id: user._id, email: user.email },
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to delete user.",
            error: error.message,
        });
    }
});

/* Backwards-compatible single-shot verify endpoint */
router.patch("/verify-user", async (req, res) => {
    try {
        const { userId, email } = req.body;

        if (!userId && !email) {
            return res.status(400).json({
                ok: false,
                message: "userId or email is required.",
            });
        }

        let query;
        if (userId) {
            if (!mongoose.Types.ObjectId.isValid(userId)) {
                return res.status(400).json({ ok: false, message: "Invalid userId." });
            }
            query = { _id: userId };
        } else {
            query = { email: String(email).toLowerCase() };
        }

        const user = await User.findOne(query);
        if (!user) {
            return res.status(404).json({ ok: false, message: "User not found." });
        }

        if (!user.isVerified) {
            user.isVerified = true;
            await user.save();
        }

        return res.status(200).json({
            ok: true,
            message: "User verified.",
            user: {
                id: user._id,
                name: user.name,
                email: user.email,
                phone: user.phone,
                isVerified: user.isVerified,
            },
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to verify user.",
            error: error.message,
        });
    }
});

/* ============================================================
 *  PROJECTS
 * ============================================================ */
function normalizeServicePayload(service) {
    return {
        internalBaseUrl: service?.internalBaseUrl || "",
        healthPath: service?.healthPath || "/health",
        enabled: typeof service?.enabled === "boolean" ? service.enabled : true,
        authMode: service?.authMode || "service-token",
        requiredScopes: Array.isArray(service?.requiredScopes)
            ? service.requiredScopes
            : [],
    };
}

router.get("/projects", async (_req, res) => {
    try {
        const projects = await Project.find().sort({ createdAt: -1 });
        return res.status(200).json({
            ok: true,
            count: projects.length,
            projects,
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to load projects.",
            error: error.message,
        });
    }
});

router.post("/projects", async (req, res) => {
    try {
        const {
            name,
            slug,
            description,
            projectUrl,
            status,
            lastActiveAt,
            service,
        } = req.body;

        if (!name || !slug) {
            return res.status(400).json({
                ok: false,
                message: "name and slug are required.",
            });
        }

        const project = await Project.create({
            name,
            slug,
            description,
            projectUrl,
            status,
            lastActiveAt,
            service: normalizeServicePayload(service),
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

router.patch("/projects/:id", async (req, res) => {
    try {
        const { id } = req.params;

        if (!mongoose.Types.ObjectId.isValid(id)) {
            return res.status(400).json({ ok: false, message: "Invalid project id." });
        }

        const allowed = [
            "name",
            "slug",
            "description",
            "projectUrl",
            "status",
            "lastActiveAt",
            "service",
        ];

        const update = {};
        for (const field of allowed) {
            if (Object.prototype.hasOwnProperty.call(req.body, field)) {
                update[field] = req.body[field];
            }
        }

        if (Object.prototype.hasOwnProperty.call(update, "service")) {
            update.service = normalizeServicePayload(update.service);
        }

        const project = await Project.findByIdAndUpdate(id, update, {
            new: true,
            runValidators: true,
        });

        if (!project) {
            return res.status(404).json({ ok: false, message: "Project not found." });
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

router.delete("/projects/:id", async (req, res) => {
    try {
        const { id } = req.params;

        if (!mongoose.Types.ObjectId.isValid(id)) {
            return res.status(400).json({ ok: false, message: "Invalid project id." });
        }

        const project = await Project.findByIdAndDelete(id);
        if (!project) {
            return res.status(404).json({ ok: false, message: "Project not found." });
        }

        return res.status(200).json({
            ok: true,
            message: "Project deleted.",
            project: { id: project._id, slug: project.slug },
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to delete project.",
            error: error.message,
        });
    }
});

module.exports = router;
