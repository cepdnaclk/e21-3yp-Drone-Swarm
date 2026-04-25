const { MongoClient, ServerApiVersion } = require("mongodb");
const { config } = require("dotenv");

config();

const MONGODB_URI = process.env.MONGODB_URI || process.env.DATABASE_URL;
const MONGODB_DB_NAME = process.env.MONGODB_DB_NAME || "drone_swarm";

if (!MONGODB_URI) {
    throw new Error(
        "Missing env vars. Set MONGODB_URI (or DATABASE_URL)."
    );
}

const client = new MongoClient(MONGODB_URI, {
    serverApi: {
        version: ServerApiVersion.v1,
        strict: true,
        deprecationErrors: true,
    },
});

let db = null;
let connectPromise = null;

async function initializeDatabase() {
    if (db) {
        return db;
    }

    if (!connectPromise) {
        connectPromise = client
            .connect()
            .then(() => {
                db = client.db(MONGODB_DB_NAME);
                return db;
            })
            .catch((error) => {
                connectPromise = null;
                throw error;
            });
    }

    return connectPromise;
}

initializeDatabase().catch((error) => {
    console.error("Database initialization failed:", error.message);
});

function getDb() {
    if (!db) {
        throw new Error(
            "Database is not initialized. Call initializeDatabase() before getDb()."
        );
    }

    return db;
}

module.exports = {
    get db() {
        return db;
    },
    client,
    getDb,
    initializeDatabase,
};
