# Security Policy

## Hackathon proof of concept

ZeroWall is a hackathon proof of concept, not production security software. It demonstrates an MTD-inspired adaptive-hardening workflow against the intentionally vulnerable FastAPI application included in this repository.

Do not expose the demo services to untrusted networks, use ZeroWall to protect production systems, or point its attack-replay components at systems you do not own and control.

## Simulated vulnerabilities and attacks

All bundled vulnerabilities and attack payloads are deliberately constrained for safe demonstration:

- File-access behavior uses an in-memory dictionary and never reads arbitrary host files.
- Command-injection behavior uses predefined in-memory responses and never executes operating-system commands.
- SQL-injection behavior uses an in-memory list and never connects to a database.
- Exploit replay uses predefined, non-destructive HTTP requests targeting only the bundled local demo application.
- No network scanning, credential collection, persistence, malware, or general-purpose exploitation capability is included.
- Deployment writes only to ZeroWall's local, versioned demo artifact directory.

The class named `CandidateSandbox` launches temporary local subprocesses for candidate evaluation. It provides process and file separation for the controlled demo, but it is not an OS-level security sandbox. Do not use it to execute arbitrary or untrusted source code.

The Core API is intended for a controlled local demo environment and does not provide production authentication or authorization.

## Reporting a real vulnerability

Please do not disclose genuine vulnerabilities in public issues.

Use GitHub's private security advisory feature for this repository when available. If private advisories are unavailable, contact the repository maintainer privately through their GitHub profile with:

- A description of the issue and its potential impact
- Reproduction steps or a minimal proof of concept
- The affected commit or version
- Any suggested mitigation

Please limit testing to systems and accounts you own or have explicit permission to test.

## Supported versions

Only the latest version on the default branch receives best-effort fixes. No version of ZeroWall is currently supported for production use.

## License

ZeroWall is distributed under the [Apache License 2.0](LICENSE).
