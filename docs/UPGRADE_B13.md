# Upgrade RepoMind from b12 to b13

[RepoMind v2.0.0b13](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b13) was published as a GitHub prerelease on
November 15, 2026. Use the exact [wheel](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13-py3-none-any.whl) with SHA-256
`6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9`, or consult the published
[checksum file](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/SHA256SUMS.txt). The [source distribution](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13.tar.gz)
has SHA-256 `eae981560f5777dcac85da01d509f38c11d7937db63b0326122f42aa045a6d85`.
The similarly named PyPI distribution is unrelated; install the verified GitHub wheel.

1. Stop RepoMind MCP and watch processes that use the environment.
2. Record the existing version and back up valuable repository memory/index data under .repomind. Preserve your repository working tree.
3. Download the exact b13 wheel attached to the release and compare SHA-256 with that asset's published value.
4. Use the existing RepoMind virtual environment's Python, without changing system Python or PATH.

Windows PowerShell:

~~~powershell
$WheelPath = (Resolve-Path "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl").Path
$Expected = "6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9"
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $WheelPath).Hash.ToLowerInvariant() -ne $Expected) { throw "RepoMind wheel checksum mismatch" }
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install --upgrade $WheelPath
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip check
& "C:\Tools\RepoMind\Scripts\repomind.exe" --version
~~~

Linux, using your existing environment (download the wheel above first):

~~~sh
printf '%s  %s\n' '6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9' 'repomind-2.0.0b13-py3-none-any.whl' | sha256sum --check - &&
"/path/to/repomind-venv/bin/python" -m pip install --upgrade ./repomind-2.0.0b13-py3-none-any.whl &&
"/path/to/repomind-venv/bin/python" -m pip check &&
"/path/to/repomind-venv/bin/repomind" --version
~~~

The expected reported version is `2.0.0b13`. On macOS, compare with `shasum -a 256`; macOS remains unvalidated. The shell checksum examples above target Linux.

If you use optional Tree-sitter or watch dependencies, retain corresponding extras when installing the verified wheel, for example python -m pip install --upgrade "/path/to/repomind-2.0.0b13-py3-none-any.whl[treesitter,watch]". Confirm grammar availability with repomind doctor.

Check repomind status -C <repository> and repomind doctor <repository>, then restart your MCP client/watch process. Investigate index warnings before forcing a rebuild; forced reindexing is not a substitute for backing up manual memory. This guide does not claim a newly executed complete b12-to-b13 data-migration lifecycle test.

To roll back, stop processes, reinstall the separately hash-verified published b12 wheel and restore backed-up local data if required. Its historical public wheel SHA-256 remains 34c751e3ffb893bcc07403d4bdf2f6d1c5154ac04e4afcac92bbdfadcf43b827.
