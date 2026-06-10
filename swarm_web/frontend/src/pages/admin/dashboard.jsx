import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

function AdminDashboard() {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        let mounted = true;

        async function load() {
            setLoading(true);
            setError("");
            try {
                const res = await fetch(`${apiBase}/admin/stats`, {
                    credentials: "include",
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.message || "Failed to load stats.");
                if (mounted) setStats(data.stats);
            } catch (err) {
                if (mounted) setError(err.message);
            } finally {
                if (mounted) setLoading(false);
            }
        }

        load();
        return () => { mounted = false; };
    }, []);

    return (
        <div className="admin-page">
            <header className="admin-page-header">
                <div className="section-kicker">Administration</div>
                <h1 className="console-heading">Dashboard</h1>
                <p className="auth-copy">Overview of users and project services across the swarm.</p>
            </header>

            {loading && <div className="status-box">Loading stats...</div>}
            {error && <div className="status-box is-error">{error}</div>}

            {stats && (
                <>
                    <section className="stats-grid">
                        <StatCard label="Users" value={stats.users.total} sub={`${stats.users.verified} verified`} />
                        <StatCard
                            label="Pending"
                            value={stats.users.pending}
                            sub="awaiting approval"
                            highlight={stats.users.pending > 0}
                        />
                        <StatCard label="Projects" value={stats.projects.total} sub={`${stats.projects.active + stats.projects.online} online`} />
                        <StatCard label="Maintenance" value={stats.projects.maintenance} sub="needs attention" />
                    </section>

                    {stats.users.pending > 0 && (
                        <section className="callout-card">
                            <div>
                                <div className="callout-title">
                                    {stats.users.pending} user{stats.users.pending === 1 ? "" : "s"} awaiting approval
                                </div>
                                <div className="callout-sub">
                                    Review and verify so they can access the console.
                                </div>
                            </div>
                            <Link to="/admin/users?status=pending" className="primary-button">
                                Review pending
                            </Link>
                        </section>
                    )}

                    <section className="stats-grid">
                        <StatCard label="Active" value={stats.projects.active} sub="status: active" />
                        <StatCard label="Online" value={stats.projects.online} sub="status: online" />
                        <StatCard label="Maintenance" value={stats.projects.maintenance} sub="status: maintenance" />
                        <StatCard label="Offline" value={stats.projects.offline} sub="status: offline" />
                    </section>
                </>
            )}
        </div>
    );
}

function StatCard({ label, value, sub, highlight }) {
    return (
        <div className={`metric-card ${highlight ? "is-highlight" : ""}`}>
            <div className="metric-label">{label}</div>
            <div className="metric-value">{value}</div>
            <div className="metric-sub">{sub}</div>
        </div>
    );
}

export default AdminDashboard;
