const express = require("express");
const { initializeDatabase, getDb } = require("./database");

const app = express();
const PORT = process.env.PORT || 5000;

app.use(express.json());

async function testMongoConnection() {
    await initializeDatabase();
    const db = getDb();

    // Ping confirms Atlas connection and credentials are valid.
    await db.command({ ping: 1 });

    return {
        ok: true,
        message: "MongoDB connection is working.",
        database: db.databaseName,
    };
}

app.get("/health", (_req, res) => {
    res.status(200).json({ ok: true, service: "backend" });
});

app.get("/health/db", async (_req, res) => {
    try {
        const result = await testMongoConnection();
        return res.status(200).json(result);
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "MongoDB connection failed.",
            error: error.message,
        });
    }
});

app.listen(PORT, async () => {
    console.log(`Server running on port ${PORT}`);

    try {
        const result = await testMongoConnection();
        console.log(result.message, `Database: ${result.database}`);
    } catch (error) {
        console.error("MongoDB startup connection test failed:", error.message);
    }
});
