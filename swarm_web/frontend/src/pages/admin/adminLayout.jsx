import { NavLink, Outlet, useNavigate } from "react-router-dom";

function AdminLayout({ user, onLogout }) {
    const navigate = useNavigate();

    return (
        <main className="page-shell admin-shell">
            <aside className="admin-sidebar">
                <div className="admin-brand">
                    <div className="brand-mark-badge" />
                    <div>
                        <strong>PeraSwarm</strong>
                        <div className="admin-brand-sub">Admin Console</div>
                    </div>
                </div>

                <nav className="admin-nav">
                    <NavLink to="/admin" end className="admin-nav-link">
                        Dashboard
                    </NavLink>
                    <NavLink to="/admin/users" className="admin-nav-link">
                        Users
                    </NavLink>
                    <NavLink to="/admin/projects" className="admin-nav-link">
                        Projects
                    </NavLink>
                </nav>

                <div className="admin-sidebar-foot">
                    <div className="admin-user">
                        <div className="admin-user-name">{user?.email || "admin"}</div>
                        <div className="admin-user-role">Administrator</div>
                    </div>
                    <button
                        type="button"
                        className="logout-button"
                        onClick={() => navigate("/projects")}
                    >
                        Back to Console
                    </button>
                    <button
                        type="button"
                        className="logout-button"
                        onClick={onLogout}
                    >
                        Logout
                    </button>
                </div>
            </aside>

            <section className="admin-content">
                <Outlet />
            </section>
        </main>
    );
}

export default AdminLayout;
