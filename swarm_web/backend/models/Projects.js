const mongoose = require("mongoose");

const projectSchema = new mongoose.Schema(
    {
        name: {
            type: String,
            required: true,
            trim: true,
        },
        slug: {
            type: String,
            required: true,
            unique: true,
            trim: true,
            lowercase: true,
        },
        description: {
            type: String,
            default: "",
        },
        projectUrl: {
            type: String,
            trim: true,
            default: "",
        },
        service: {
            internalBaseUrl: {
                type: String,
                trim: true,
                default: "",
            },
            healthPath: {
                type: String,
                trim: true,
                default: "/health",
            },
            enabled: {
                type: Boolean,
                default: true,
            },
            authMode: {
                type: String,
                enum: ["none", "service-token"],
                default: "service-token",
            },
            requiredScopes: {
                type: [String],
                default: [],
            },
        },
        status: {
            type: String,
            enum: ["active", "online", "maintenance", "offline"],
            default: "offline",
        },
        lastActiveAt: {
            type: Date,
            default: Date.now,
        },
    },
    {
        timestamps: true,
    }
);

const Project = mongoose.model("Project", projectSchema);

module.exports = Project;
