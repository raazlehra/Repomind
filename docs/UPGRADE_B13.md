# Upgrade RepoMind from b12 to b13

b13 is pending owner publication approval. These steps apply only after the canonical [GitHub Releases page](https://github.com/raazlehra/Repomind/releases) actually lists b13 assets. Do not guess download URLs or reuse b12/RC2 hashes for a different build.

1. Stop RepoMind MCP and watch processes that use the environment.
2. Record the existing version and back up valuable repository memory/index data under .repomind. Preserve your repository working tree.
3. Download the exact b13 wheel attached to the release and compare SHA-256 with that asset's published value.
4. Use the existing RepoMind virtual environment's Python, without changing system Python or PATH.

Windows PowerShell:

~~~powershell
$WheelPath = (Resolve-Path "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl").Path
Get-FileHash -Algorithm SHA256 -LiteralPath $WheelPath
# Compare the actual published asset hash before continuing.
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install --upgrade $WheelPath
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip check
& "C:\Tools\RepoMind\Scripts\repomind.exe" --version
~~~

POSIX, using your existing environment:

~~~sh
sha256sum ./repomind-2.0.0b13-py3-none-any.whl
# On macOS use shasum -a 256 instead; compare the published hash.
"/path/to/repomind-venv/bin/python" -m pip install --upgrade ./repomind-2.0.0b13-py3-none-any.whl
"/path/to/repomind-venv/bin/python" -m pip check
"/path/to/repomind-venv/bin/repomind" --version
~~~

If you use optional Tree-sitter or watch dependencies, retain corresponding extras when installing the verified wheel, for example python -m pip install --upgrade "/path/to/repomind-2.0.0b13-py3-none-any.whl[treesitter,watch]". Confirm grammar availability with repomind doctor.

Check repomind status -C <repository> and repomind doctor <repository>, then restart your MCP client/watch process. Investigate index warnings before forcing a rebuild; forced reindexing is not a substitute for backing up manual memory. This guide does not claim a newly executed complete b12-to-b13 data-migration lifecycle test.

To roll back, stop processes, reinstall the separately hash-verified published b12 wheel and restore backed-up local data if required. Its historical public wheel SHA-256 remains 34c751e3ffb893bcc07403d4bdf2f6d1c5154ac04e4afcac92bbdfadcf43b827.
