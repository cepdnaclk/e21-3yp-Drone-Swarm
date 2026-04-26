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
                const response = await fetch(`${apiBase}/projects`);
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.message || "Failed to load projects.");
                }

                if (mounted) {
                    setProjects(Array.isArray(data.projects) ? data.projects : []);
                }
            } catch (fetchError) {
                if (mounted) {
                    setError(fetchError.message || "Failed to load projects.");
                }
            } finally {
                if (mounted) {
                    setLoading(false);
                }
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
            const combined = [project.name, project.slug, project.description]
                .join(" ")
                .toLowerCase();

            if (filter === "online" && !["active", "online"].includes(status)) {
                return false;
            }

            if (query && !combined.includes(query.toLowerCase())) {
                return false;
            }

            return true;
        });
    }, [projects, filter, query]);

    const stats = useMemo(() => {
        const onlineCount = projects.filter((project) => {
            const status = String(project.status || "offline").toLowerCase();
            return status === "active" || status === "online";
        }).length;

        const withUrls = projects.filter((project) => Boolean(project.projectUrl)).length;

        return {
            total: projects.length,
            onlineCount,
            withUrls,
            leads: new Set(
                projects
                    .map((project) =>
                        typeof project.lead === "object" && project.lead !== null
                            ? project.lead.name
                            : ""
                    )
                    .filter(Boolean)
            ).size,
        };
    }, [projects]);

    return (
        <div style={styles.page}>
            <div style={styles.texture} />
            <header style={styles.topBar}>
                <div>
                    <div style={styles.miniLabel}>A Programming Framework for Robot Swarms</div>
                    <h1 style={styles.title}>Your projects</h1>
                    <p style={styles.subtitle}>
                        Select a project workspace and open its page directly from the console.
                    </p>
                </div>

                <div style={styles.headerActions}>
                    <div style={styles.searchWrap}>
                        <input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search projects..."
                            style={styles.searchInput}
                        />
                    </div>

                    <div style={styles.segment}>
                        <button
                            type="button"
                            style={{ ...styles.segmentBtn, ...(filter === "all" ? styles.segmentActive : {}) }}
                            onClick={() => setFilter("all")}
                        >
                            All
                        </button>
                        <button
                            type="button"
                            style={{ ...styles.segmentBtn, ...(filter === "online" ? styles.segmentActive : {}) }}
                            onClick={() => setFilter("online")}
                        >
                            Online
                        </button>
                    </div>

                    <button type="button" onClick={onLogout} style={styles.logoutBtn}>
                        Logout
                    </button>
                </div>
            </header>

            <section style={styles.statsGrid}>
                <StatCard label="Projects" value={String(stats.total)} sub={`${stats.onlineCount} online`} />
                <StatCard label="With URL" value={String(stats.withUrls)} sub="project pages linked" />
                <StatCard label="Leads" value={String(stats.leads)} sub="active researchers" />
                <StatCard
                    label="Showing"
                    value={String(filteredProjects.length)}
                    sub={query ? `for \"${query}\"` : "current filter"}
                />
            </section>

            {loading ? <div style={styles.stateBox}>Loading projects...</div> : null}
            {error ? <div style={{ ...styles.stateBox, ...styles.errorBox }}>{error}</div> : null}

            {!loading && !error ? (
                <section style={styles.grid}>
                    {filteredProjects.map((project) => (
                        <ProjectCard key={project._id || project.slug} project={project} />
                    ))}
                </section>
            ) : null}
        </div>
    );
}

function ProjectCard({ project }) {
    const statusKey = String(project.status || "offline").toLowerCase();
    const status = statusMap[statusKey] || statusMap.offline;

    const leadName =
        typeof project.lead === "object" && project.lead !== null
            ? project.lead.name || project.lead.email || "Unknown"
            : "Unknown";

    const hasUrl = Boolean(project.projectUrl);

    return (
        <article style={styles.card}>
            <div style={styles.cardHeader}>
                <div style={styles.iconShell}>
                    <div style={styles.iconDot} />
                </div>
                <span style={{ ...styles.statusPill, color: status.color, background: status.bg }}>
                    {status.label}
                </span>
            </div>

            <h3 style={styles.cardTitle}>{project.name || "Untitled Project"}</h3>
            <div style={styles.cardSlug}>/{project.slug || "n-a"}</div>
            <p style={styles.cardDesc}>{project.description || "No description provided."}</p>

            <div style={styles.metaRow}>
                <div style={styles.metaItem}>Lead: {leadName}</div>
                <div style={styles.metaItem}>Updated: {formatDate(project.updatedAt)}</div>
            </div>

            {hasUrl ? (
                <a
                    href={project.projectUrl}
                    target="_blank"
                    rel="noreferrer"
                    style={styles.openLink}
                >
                    Open project page
                </a>
            ) : (
                <span style={styles.noLink}>No URL configured</span>
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

function formatDate(value) {
    if (!value) {
        return "-";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return "-";
    }

    return date.toLocaleDateString();
}

const styles = {
    page: {
        minHeight: "100vh",
        padding: "28px 34px 46px",
        boxSizing: "border-box",
        background: "radial-gradient(circle at 0% 0%, #f8fafc 0%, #eef2f7 40%, #f7f7f5 100%)",
        fontFamily: '"Sora", "Manrope", "Segoe UI", sans-serif',
        color: "#111827",
        position: "relative",
    },
    texture: {
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        backgroundImage:
            "linear-gradient(rgba(17, 24, 39, 0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(17, 24, 39, 0.03) 1px, transparent 1px)",
        backgroundSize: "30px 30px",
        maskImage: "radial-gradient(circle at center, black 40%, transparent 85%)",
    },
    topBar: {
        position: "relative",
        zIndex: 1,
        display: "flex",
        justifyContent: "space-between",
        gap: 20,
        alignItems: "flex-start",
        flexWrap: "wrap",
        marginBottom: 20,
    },
    miniLabel: {
        fontSize: 11,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        fontWeight: 600,
        color: "#4b5563",
        marginBottom: 10,
    },
    title: {
        margin: 0,
        fontSize: "clamp(26px, 4vw, 34px)",
        letterSpacing: "-0.02em",
        lineHeight: 1.06,
    },
    subtitle: {
        marginTop: 8,
        color: "#4b5563",
        fontSize: 14,
        maxWidth: 560,
    },
    headerActions: {
        display: "flex",
        gap: 10,
        alignItems: "center",
        flexWrap: "wrap",
    },
    searchWrap: {
        minWidth: 220,
        flex: "1 1 240px",
    },
    searchInput: {
        width: "100%",
        height: 40,
        border: "1px solid #d1d5db",
        borderRadius: 10,
        padding: "0 12px",
        fontSize: 14,
        background: "#ffffff",
        boxSizing: "border-box",
    },
    segment: {
        display: "inline-flex",
        borderRadius: 10,
        border: "1px solid #d1d5db",
        background: "#ffffff",
        overflow: "hidden",
    },
    segmentBtn: {
        border: "none",
        background: "transparent",
        color: "#334155",
        padding: "8px 12px",
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
    },
    segmentActive: {
        background: "#111827",
        color: "#ffffff",
    },
    logoutBtn: {
        border: "1px solid #cbd5e1",
        background: "#ffffff",
        color: "#1f2937",
        borderRadius: 10,
        height: 40,
        padding: "0 14px",
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
    },
    statsGrid: {
        position: "relative",
        zIndex: 1,
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 10,
        marginBottom: 18,
    },
    statCard: {
        background: "rgba(255, 255, 255, 0.9)",
        border: "1px solid #dbe3ee",
        borderRadius: 14,
        padding: "14px 16px",
        backdropFilter: "blur(1px)",
    },
    statLabel: {
        fontSize: 10,
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        color: "#6b7280",
        fontWeight: 700,
    },
    statValue: {
        marginTop: 6,
        fontSize: 24,
        fontWeight: 700,
        letterSpacing: "-0.01em",
    },
    statSub: {
        marginTop: 2,
        fontSize: 12,
        color: "#6b7280",
    },
    stateBox: {
        position: "relative",
        zIndex: 1,
        background: "#ffffff",
        border: "1px solid #dbe3ee",
        borderRadius: 12,
        padding: "12px 14px",
        fontSize: 13,
        marginBottom: 12,
    },
    errorBox: {
        color: "#b91c1c",
        borderColor: "#fecaca",
        background: "#fef2f2",
    },
    grid: {
        position: "relative",
        zIndex: 1,
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 12,
    },
    card: {
        background: "rgba(255, 255, 255, 0.94)",
        border: "1px solid #dbe3ee",
        borderRadius: 14,
        padding: 16,
        boxShadow: "0 8px 24px rgba(15, 23, 42, 0.04)",
    },
    cardHeader: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 12,
    },
    iconShell: {
        width: 34,
        height: 34,
        borderRadius: 10,
        border: "1px solid #dbe3ee",
        background: "linear-gradient(160deg, #eaf2ff 0%, #f8fafc 100%)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
    },
    iconDot: {
        width: 12,
        height: 12,
        borderRadius: 999,
        background: "#1d4ed8",
        boxShadow: "0 0 0 3px rgba(29, 78, 216, 0.15)",
    },
    statusPill: {
        fontSize: 11,
        padding: "5px 8px",
        borderRadius: 999,
        fontWeight: 700,
    },
    cardTitle: {
        margin: 0,
        fontSize: 17,
        letterSpacing: "-0.01em",
    },
    cardSlug: {
        marginTop: 4,
        fontSize: 12,
        color: "#64748b",
        fontFamily: '"JetBrains Mono", "Consolas", monospace',
    },
    cardDesc: {
        marginTop: 10,
        marginBottom: 12,
        fontSize: 13,
        color: "#475569",
        lineHeight: 1.5,
        minHeight: 58,
    },
    metaRow: {
        display: "flex",
        flexDirection: "column",
        gap: 6,
        marginBottom: 12,
    },
    metaItem: {
        fontSize: 12,
        color: "#6b7280",
    },
    openLink: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "100%",
        height: 36,
        borderRadius: 10,
        border: "1px solid #dbe3ee",
        background: "#ffffff",
        color: "#0f172a",
        textDecoration: "none",
        fontSize: 12,
        fontWeight: 700,
    },
    noLink: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "100%",
        height: 36,
        borderRadius: 10,
        border: "1px dashed #cbd5e1",
        color: "#64748b",
        fontSize: 12,
        fontWeight: 600,
    },
};

export default ProjectPage;
