import { useEffect, useMemo, useState } from "react";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

const statusMap = {
    active: { label: "Active", color: "#0f766e", bg: "#e6fffb" },
    online: { label: "Online", color: "#166534", bg: "#ecfdf3" },
    maintenance: { label: "Maintenance", color: "#92400e", bg: "#fffbeb" },
    offline: { label: "Offline", color: "#6b7280", bg: "#f3f4f6" },
};

function ProjectPage({ onLogout }) {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [query, setQuery] = useState("");
    const [filter, setFilter] = useState("all");

    useEffect(() => {
        let mounted = true;

        async function fetchProjects() {
            setLoading(true);
            setError("");

            try {
                const response = await fetch(`${apiBase}/projects`, {
                    method: "GET",
                    credentials: "include", 
                });

                // Check for non-JSON responses (like 500 HTML errors) before parsing
                const textData = await response.text();
                let data;
                try {
                    data = JSON.parse(textData);
                } catch (e) {
                    throw new Error("Server returned an invalid response.");
                }

                if (!response.ok) {
                    throw new Error(data.message || "Failed to load projects.");
                }

                if (mounted) {
                    // Safely handle both [...] and { projects: [...] } backend responses
                    const projectsList = Array.isArray(data) 
                        ? data 
                        : (Array.isArray(data.projects) ? data.projects : []);
                    setProjects(projectsList);
                }
            } catch (err) {
                if (mounted) {
                    setError(err.message || "Failed to load projects.");
                }
            } finally {
                if (mounted) setLoading(false);
            }
        }

        fetchProjects();

        return () => {
            mounted = false;
        };
    }, []);

    const filteredProjects = useMemo(() => {
        return projects.filter((project) => {
            const status = String(project.status || "offline").toLowerCase();

            // filter(Boolean) prevents undefined fields from messing up the search string
            const text = [project.name, project.slug, project.description]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();

            if (filter === "online" && !["active", "online"].includes(status)) {
                return false;
            }

            if (query && !text.includes(query.toLowerCase())) {
                return false;
            }

            return true;
        });
    }, [projects, filter, query]);

    const stats = useMemo(() => {
        const onlineCount = projects.filter((p) => {
            const s = String(p.status || "offline").toLowerCase();
            return s === "active" || s === "online";
        }).length;

        const withUrls = projects.filter((p) => p.projectUrl).length;

        return {
            total: projects.length,
            onlineCount,
            withUrls,
            gatewayEnabled: 0,
        };
    }, [projects]);

    return (
        <div style={styles.page}>
            <div style={styles.texture} />

            {/* HEADER */}
            <header style={styles.topBar}>
                <div>
                    <div style={styles.miniLabel}>
                        A Programming Framework for Robot Swarms
                    </div>
                    <h1 style={styles.title}>Your projects</h1>
                    <p style={styles.subtitle}>
                        Select a project workspace and open its page directly from the console.
                    </p>
                </div>

                <div style={styles.headerActions}>
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search projects..."
                        style={styles.searchInput}
                    />

                    <div style={styles.segment}>
                        <button
                            type="button"
                            style={{
                                ...styles.segmentBtn,
                                ...(filter === "all" ? styles.segmentActive : {}),
                            }}
                            onClick={() => setFilter("all")}
                        >
                            All
                        </button>

                        <button
                            type="button"
                            style={{
                                ...styles.segmentBtn,
                                ...(filter === "online" ? styles.segmentActive : {}),
                            }}
                            onClick={() => setFilter("online")}
                        >
                            Online
                        </button>
                    </div>

                    <button onClick={onLogout} style={styles.logoutBtn}>
                        Logout
                    </button>
                </div>
            </header>

            {/* STATS */}
            <section style={styles.statsGrid}>
                <StatCard label="Projects" value={stats.total} sub={`${stats.onlineCount} online`} />
                <StatCard label="With URL" value={stats.withUrls} sub="project pages linked" />
                <StatCard label="Gateway" value={stats.gatewayEnabled} sub="services enabled" />
                <StatCard label="Showing" value={filteredProjects.length} sub="filtered results" />
            </section>

            {/* LOADING / ERROR */}
            {loading && <div style={styles.stateBox}>Loading projects...</div>}
            {error && <div style={{ ...styles.stateBox, ...styles.errorBox }}>{error}</div>}

            {/* GRID */}
            {!loading && !error && (
                <section style={styles.grid}>
                    {filteredProjects.length === 0 ? (
                        <div style={{...styles.stateBox, gridColumn: "1 / -1"}}>No projects found.</div>
                    ) : (
                        filteredProjects.map((project) => (
                            <ProjectCard key={project._id || project.slug || Math.random()} project={project} />
                        ))
                    )}
                </section>
            )}
        </div>
    );
}

function ProjectCard({ project }) {
    const status = statusMap[project.status?.toLowerCase()] || statusMap.offline;

    return (
        <article style={styles.card}>
            <div style={styles.cardHeader}>
                <span style={{ ...styles.statusPill, color: status.color, background: status.bg }}>
                    {status.label}
                </span>
            </div>

            <h3 style={styles.cardTitle}>{project.name || "Unnamed Project"}</h3>
            <div style={styles.cardSlug}>/{project.slug || "no-slug"}</div>

            <p style={styles.cardDesc}>{project.description || "No description provided."}</p>

            <div style={styles.metaItem}>
                Updated: {project.updatedAt ? new Date(project.updatedAt).toLocaleDateString() : "Just now"}
            </div>

            {project.projectUrl ? (
                <a href={project.projectUrl} target="_blank" rel="noreferrer" style={styles.openLink}>
                    Open project
                </a>
            ) : (
                <div style={styles.noLink}>No URL configured</div>
            )}
        </article>
    );
}

function StatCard({ label, value, sub }) {
    return (
        <div style={styles.statCard}>
            <div style={styles.statLabel}>{label}</div>
            <div style={styles.statValue}>{value}</div>
            <div style={styles.statSub}>{sub}</div>
        </div>
    );
}

const styles = {
    page: {
        boxSizing: "border-box", // 🔥 Fixed horizontal scroll issue
        minHeight: "100vh",
        width: "100vw",
        marginLeft: "calc(50% - 50vw)",
        padding: 28,
        background: "#f7f7f5",
    },
    texture: {},
    topBar: {
        display: "flex",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
        marginBottom: 20,
    },
    miniLabel: { fontSize: 11, textTransform: "uppercase", color: "#6b7280" },
    title: { fontSize: 32, margin: 0 },
    subtitle: { fontSize: 14, color: "#4b5563" },
    headerActions: { display: "flex", gap: 10, flexWrap: "wrap" },

    searchInput: {
        padding: 10,
        borderRadius: 10,
        border: "1px solid #d1d5db",
    },

    segment: {
        display: "flex",
        border: "1px solid #d1d5db",
        borderRadius: 10,
        overflow: "hidden",
    },

    segmentBtn: {
        padding: "8px 12px",
        border: "none",
        background: "white",
        cursor: "pointer",
    },

    segmentActive: {
        background: "#111827",
        color: "white",
    },

    logoutBtn: {
        padding: "8px 12px",
        borderRadius: 10,
        border: "1px solid #ccc",
        background: "white",
        cursor: "pointer",
    },

    statsGrid: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 10,
        marginBottom: 20,
    },

    statCard: {
        background: "white",
        padding: 14,
        borderRadius: 12,
        border: "1px solid #e5e7eb",
    },

    statLabel: { fontSize: 11, color: "#6b7280" },
    statValue: { fontSize: 22, fontWeight: "bold" },
    statSub: { fontSize: 12, color: "#6b7280" },

    stateBox: {
        padding: 12,
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 10,
        marginBottom: 10,
    },

    errorBox: { color: "red", backgroundColor: "#fef2f2" },

    grid: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
        gap: 12,
    },

    card: {
        background: "white",
        padding: 14,
        borderRadius: 12,
        border: "1px solid #e5e7eb",
    },

    cardHeader: { marginBottom: 8 },
    statusPill: { padding: "4px 8px", borderRadius: 999, fontSize: 11, fontWeight: "bold" },
    cardTitle: { margin: 0 },
    cardSlug: { fontFamily: "monospace", fontSize: 12, color: "#6b7280" },
    cardDesc: { fontSize: 13, color: "#4b5563" },

    metaItem: { fontSize: 12, color: "#6b7280", marginTop: 8 },

    openLink: {
        display: "block",
        marginTop: 10,
        textAlign: "center",
        padding: 8,
        border: "1px solid #ddd",
        borderRadius: 8,
        textDecoration: "none",
        color: "#111827",
        fontWeight: "500",
    },

    noLink: {
        marginTop: 10,
        fontSize: 12,
        color: "#9ca3af",
        padding: 8,
        textAlign: "center",
        border: "1px dashed #e5e7eb",
        borderRadius: 8,
    },
};

export default ProjectPage;