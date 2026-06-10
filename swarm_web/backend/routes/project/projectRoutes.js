const express = require("express");
const Project = require("../../models/Projects");
const { authenticateJWT } = require("../../middleware/auth");

const router = express.Router();

router.get("/", authenticateJWT, async (_req, res) => {
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
            message: "Failed to fetch projects.",
            error: error.message,
        });
    }
});

module.exports = router;
