import { useEffect, useMemo, useState } from "react";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

const statusMap = {
    active: { label: "Active", color: "#0f766e", bg: "rgba(132, 245, 166, 0.14)" },
    online: { label: "Online", color: "#166534", bg: "rgba(132, 245, 166, 0.14)" },
    maintenance: { label: "Maintenance", color: "#92400e", bg: "rgba(255, 191, 105, 0.16)" },
    offline: { label: "Offline", color: "#6b7280", bg: "rgba(255, 255, 255, 0.06)" },
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

                const textData = await response.text();
                let data;

                try {
                    data = JSON.parse(textData);
                } catch {
                    throw new Error("Server returned an invalid response.");
                }

                if (!response.ok) {
                    throw new Error(data.message || "Failed to load projects.");
                }

                if (mounted) {
                    const projectsList = Array.isArray(data)
                        ? data
                        : Array.isArray(data.projects)
                            ? data.projects
                            : [];

                    setProjects(projectsList);
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
        const onlineCount = projects.filter((project) => {
            const status = String(project.status || "offline").toLowerCase();
            return status === "active" || status === "online";
        }).length;

        const withUrls = projects.filter((project) => project.projectUrl).length;

        return {
            total: projects.length,
            onlineCount,
            withUrls,
            gatewayEnabled: 0,
        };
    }, [projects]);

    return (
        <main className="page-shell app-page">
            <section className="console-panel">
                <header className="console-header">
                    <div>
                        <div className="section-kicker">A programming framework for robot swarms</div>
                        <h1 className="console-heading">Your projects</h1>
                        <p className="auth-copy">Select a project workspace and open its page directly from the console.</p>
                    </div>

                    <button onClick={onLogout} className="logout-button">Logout</button>
                </header>

                <div className="toolbar">
                    <label className="field" style={{ flex: "1 1 320px" }}>
                        <span className="toolbar-label">Search</span>
                        <input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search projects..."
                            className="search-input"
                        />
                    </label>

                    <div>
                        <div className="toolbar-label">Filter</div>
                        <div className="segment">
                            <button
                                type="button"
                                className={`segment-button ${filter === "all" ? "is-active" : ""}`}
                                onClick={() => setFilter("all")}
                            >
                                All
                            </button>
                            <button
                                type="button"
                                className={`segment-button ${filter === "online" ? "is-active" : ""}`}
                                onClick={() => setFilter("online")}
                            >
                                Online
                            </button>
                        </div>
                    </div>
                </div>

                <section className="stats-grid">
                    <StatCard label="Projects" value={stats.total} sub={`${stats.onlineCount} online`} />
                    <StatCard label="With URL" value={stats.withUrls} sub="project pages linked" />
                    <StatCard label="Gateway" value={stats.gatewayEnabled} sub="services enabled" />
                    <StatCard label="Showing" value={filteredProjects.length} sub="filtered results" />
                </section>

                {loading && <div className="status-box">Loading projects...</div>}
                {error && <div className="status-box is-error">{error}</div>}

                {!loading && !error && (
                    <section className="project-grid">
                        {filteredProjects.length === 0 ? (
                            <div className="status-box empty-state" style={{ gridColumn: "1 / -1" }}>
                                No projects found.
                            </div>
                        ) : (
                            filteredProjects.map((project, index) => (
                                <ProjectCard key={project._id || project.slug || index} project={project} />
                            ))
                        )}
                    </section>
                )}
            </section>
        </main>
    );
}

function ProjectCard({ project }) {
    const status = statusMap[project.status?.toLowerCase()] || statusMap.offline;

    return (
        <article className="project-card">
            <div className="card-top">
                <span className="status-pill" style={{ color: status.color, background: status.bg }}>
                    {status.label}
                </span>
            </div>

            <h3>{project.name || "Unnamed Project"}</h3>
            <div className="project-slug">/{project.slug || "no-slug"}</div>

            <p className="card-desc">{project.description || "No description provided."}</p>

            <div className="card-foot">
                <span className="meta-label">
                    Updated: {project.updatedAt ? new Date(project.updatedAt).toLocaleDateString() : "Just now"}
                </span>

                {project.projectUrl ? (
                    <a href={project.projectUrl} target="_blank" rel="noreferrer" className="card-link">
                        Open project
                    </a>
                ) : (
                    <div className="card-link--muted">No URL configured</div>
                )}
            </div>
        </article>
    );
}

function StatCard({ label, value, sub }) {
    return (
        <div className="metric-card">
            <div className="metric-label">{label}</div>
            <div className="metric-value">{value}</div>
            <div className="metric-sub">{sub}</div>
        </div>
    );
}

export default ProjectPage;