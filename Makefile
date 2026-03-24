.PHONY: desktop dev dev-web dev-backend dev-frontend test lint clean

# ============================================================
# Desktop App Build (Pure Rust — no Python bundling needed)
# ============================================================

# Full desktop build: Tauri compiles Rust backend + bundles frontend
desktop:
	@echo "Building AudioGrab desktop app..."
	cd frontend && bun install && bunx @tauri-apps/cli build
	@echo ""
	@echo "Desktop app built successfully!"
	@echo "   macOS:   frontend/src-tauri/target/release/bundle/dmg/"
	@echo "   Windows: frontend/src-tauri/target/release/bundle/msi/"
	@echo "   Linux:   frontend/src-tauri/target/release/bundle/deb/"

# ============================================================
# Development
# ============================================================

# Desktop dev mode (Tauri + hot-reload frontend + Rust backend)
dev:
	cd frontend && bunx @tauri-apps/cli dev

# Web mode — Python backend + Vite frontend (original workflow)
dev-web:
	uv run audiograb-api & cd frontend && bun run dev

# Run Python backend only (for web mode)
dev-backend:
	uv run audiograb-api

# Run frontend only (for web mode)
dev-frontend:
	cd frontend && bun run dev

# ============================================================
# Utilities
# ============================================================

clean:
	rm -rf frontend/src-tauri/target
	rm -rf frontend/dist

test:
	uv run pytest

lint:
	uv run ruff check .
	cd frontend && bun run lint
	cd frontend/src-tauri && cargo clippy
