"""Open a SQL Server connection through pyodbc (imported lazily)."""

DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"


def _braced(value):
    """Quote a value for an ODBC connection string."""
    return "{" + value.replace("}", "}}") + "}"


def build_connection_string(server, driver=DEFAULT_DRIVER, database="master", user=None,
                            password=None, encrypt=True, trust_server_certificate=False,
                            application_name="index-advisor"):
    """Build an ODBC connection string.

    Driver 18 encrypts by default and rejects untrusted certificates, so Encrypt and
    TrustServerCertificate are always written out. Without a user name, Windows
    (integrated) authentication is used.
    """
    parts = [
        "DRIVER=" + _braced(driver),
        "SERVER=" + server,
        "DATABASE=" + database,
        "APP=" + _braced(application_name),
        "Encrypt=" + ("yes" if encrypt else "no"),
    ]
    if trust_server_certificate:
        parts.append("TrustServerCertificate=yes")
    if user:
        parts.append("UID=" + _braced(user))
        parts.append("PWD=" + _braced(password or ""))
    else:
        parts.append("Trusted_Connection=yes")
    return ";".join(parts) + ";"


def connect(server, pyodbc_module=None, timeout=15, **options):
    """Connect in autocommit mode; `pyodbc_module` can be injected for tests."""
    pyodbc = pyodbc_module
    if pyodbc is None:
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError(
                "pyodbc is not installed; install it with: pip install 'index-advisor[sqlserver]'"
            ) from exc
    return pyodbc.connect(build_connection_string(server, **options), autocommit=True, timeout=timeout)
