import { useEffect, useMemo, useState } from "react";
import "./app-shell.css";

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
        <main className="projects-shell">
            <header className="projects-top">
                <div>
                    <p className="project-kicker">A Programming Framework for Robot Swarms</p>
                    <h1 className="projects-title">Your projects</h1>
                    <p className="projects-sub">
                        Select a project workspace and open its page directly from the console.
                    </p>
                </div>

                <div className="projects-actions">
                    <div>
                        <input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search projects..."
                            className="projects-search"
                        />
                    </div>

                    <div className="projects-segment">
                        <button
                            type="button"
                            className={filter === "all" ? "active" : ""}
                            onClick={() => setFilter("all")}
                        >
                            All
                        </button>
                        <button
                            type="button"
                            className={filter === "online" ? "active" : ""}
                            onClick={() => setFilter("online")}
                        >
                            Online
                        </button>
                    </div>

                    <button type="button" onClick={onLogout} className="projects-logout">
                        Logout
                    </button>
                </div>
            </header>

            <section className="projects-stats">
                <StatCard label="Projects" value={String(stats.total)} sub={`${stats.onlineCount} online`} />
                <StatCard label="With URL" value={String(stats.withUrls)} sub="project pages linked" />
                <StatCard label="Leads" value={String(stats.leads)} sub="active researchers" />
                <StatCard
                    label="Showing"
                    value={String(filteredProjects.length)}
                    sub={query ? `for \"${query}\"` : "current filter"}
                />
            </section>

            {loading ? <div className="projects-state">Loading projects...</div> : null}
            {error ? <div className="projects-state error">{error}</div> : null}

            {!loading && !error ? (
                <section className="projects-grid">
                    {filteredProjects.map((project) => (
                        <ProjectCard key={project._id || project.slug} project={project} />
                    ))}
                </section>
            ) : null}
        </main>
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
        <article className="project-card">
            <div className="project-card-header">
                <div className="project-icon-shell">
                    <div className="project-icon-dot" />
                </div>
                <span className="project-status-pill" style={{ color: status.color, background: status.bg }}>
                    {status.label}
                </span>
            </div>

            <h3 className="project-title">{project.name || "Untitled Project"}</h3>
            <div className="project-slug">/{project.slug || "n-a"}</div>
            <p className="project-desc">{project.description || "No description provided."}</p>

            <div className="project-meta-row">
                <div className="project-meta-item">Lead: {leadName}</div>
                <div className="project-meta-item">Updated: {formatDate(project.updatedAt)}</div>
            </div>

            {hasUrl ? (
                <a
                    href={project.projectUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="project-link"
                >
                    Open project page
                </a>
            ) : (
                <span className="project-no-link">No URL configured</span>
            )}
        </article>
    );
}

function StatCard({ label, value, sub }) {
    return (
        <div className="projects-stat">
            <div className="projects-stat-label">{label}</div>
            <div className="projects-stat-value">{value}</div>
            <div className="projects-stat-sub">{sub}</div>
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

export default ProjectPage;
