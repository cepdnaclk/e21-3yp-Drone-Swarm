const express = require("express");
const Project = require("../../models/Projects");

const router = express.Router();

router.get("/", async (_req, res) => {
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

module.exports = router;
