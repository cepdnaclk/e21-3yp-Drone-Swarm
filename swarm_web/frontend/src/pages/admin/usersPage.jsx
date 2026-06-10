import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

const TABS = [
    { id: "all", label: "All" },
    { id: "pending", label: "Pending" },
    { id: "verified", label: "Verified" },
];

function AdminUsersPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const initialStatus = searchParams.get("status") || "all";

    const [status, setStatus] = useState(initialStatus);
    const [query, setQuery] = useState("");
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [busyId, setBusyId] = useState(null);
    const [notice, setNotice] = useState("");

    const loadUsers = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const params = new URLSearchParams();
            if (status !== "all") params.set("status", status);
            if (query.trim()) params.set("q", query.trim());

            const res = await fetch(`${apiBase}/admin/users?${params.toString()}`, {
                credentials: "include",
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Failed to load users.");
            setUsers(data.users || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [status, query]);

    useEffect(() => {
        loadUsers();
    }, [loadUsers]);

    useEffect(() => {
        const next = new URLSearchParams(searchParams);
        if (status === "all") next.delete("status");
        else next.set("status", status);
        setSearchParams(next, { replace: true });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [status]);

    async function patchUser(id, body, successMessage) {
        setBusyId(id);
        setNotice("");
        setError("");
        try {
            const res = await fetch(`${apiBase}/admin/users/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Update failed.");
            setNotice(successMessage);
            setUsers((prev) => prev.map((u) => (u._id === id ? data.user : u)));
        } catch (err) {
            setError(err.message);
        } finally {
            setBusyId(null);
        }
    }

    async function deleteUser(id, email) {
        if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) return;
        setBusyId(id);
        setNotice("");
        setError("");
        try {
            const res = await fetch(`${apiBase}/admin/users/${id}`, {
                method: "DELETE",
                credentials: "include",
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Delete failed.");
            setNotice(`Deleted ${email}.`);
            setUsers((prev) => prev.filter((u) => u._id !== id));
        } catch (err) {
            setError(err.message);
        } finally {
            setBusyId(null);
        }
    }

    const counts = useMemo(() => {
        return {
            total: users.length,
            pending: users.filter((u) => !u.isVerified).length,
            verified: users.filter((u) => u.isVerified).length,
        };
    }, [users]);

    return (
        <div className="admin-page">
            <header className="admin-page-header">
                <div className="section-kicker">Administration</div>
                <h1 className="console-heading">Users</h1>
                <p className="auth-copy">Approve registrations, edit details, or remove access.</p>
            </header>

            <div className="toolbar">
                <label className="field" style={{ flex: "1 1 320px" }}>
                    <span className="toolbar-label">Search</span>
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search by name, email, phone..."
                        className="search-input"
                    />
                </label>

                <div>
                    <div className="toolbar-label">Filter</div>
                    <div className="segment">
                        {TABS.map((tab) => (
                            <button
                                key={tab.id}
                                type="button"
                                className={`segment-button ${status === tab.id ? "is-active" : ""}`}
                                onClick={() => setStatus(tab.id)}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {notice && <div className="alert alert-success">{notice}</div>}
            {error && <div className="alert alert-error">{error}</div>}

            <div className="data-table-wrap">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Email</th>
                            <th>Phone</th>
                            <th>Status</th>
                            <th>Joined</th>
                            <th className="data-table-actions">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="6" className="data-empty">Loading users...</td></tr>
                        ) : users.length === 0 ? (
                            <tr><td colSpan="6" className="data-empty">No users found.</td></tr>
                        ) : (
                            users.map((user) => (
                                <tr key={user._id}>
                                    <td>{user.name}</td>
                                    <td>{user.email}</td>
                                    <td>{user.phone}</td>
                                    <td>
                                        <span className={`status-pill ${user.isVerified ? "is-verified" : "is-pending"}`}>
                                            {user.isVerified ? "Verified" : "Pending"}
                                        </span>
                                    </td>
                                    <td>{user.createdAt ? new Date(user.createdAt).toLocaleDateString() : "—"}</td>
                                    <td className="data-table-actions">
                                        {user.isVerified ? (
                                            <button
                                                className="ghost-button"
                                                disabled={busyId === user._id}
                                                onClick={() => patchUser(user._id, { isVerified: false }, `Unverified ${user.email}.`)}
                                            >
                                                Unverify
                                            </button>
                                        ) : (
                                            <button
                                                className="primary-button primary-button--sm"
                                                disabled={busyId === user._id}
                                                onClick={() => patchUser(user._id, { isVerified: true }, `Verified ${user.email}.`)}
                                            >
                                                Verify
                                            </button>
                                        )}
                                        <button
                                            className="danger-button"
                                            disabled={busyId === user._id}
                                            onClick={() => deleteUser(user._id, user.email)}
                                        >
                                            Delete
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            <div className="data-table-footer">
                Showing {counts.total} · {counts.pending} pending · {counts.verified} verified
            </div>
        </div>
    );
}

export default AdminUsersPage;
