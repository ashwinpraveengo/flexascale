#!/usr/bin/env bash
# Presentation startup: identical to `start_review.sh --demo` (readiness report + demo sequence).
exec "$(dirname "${BASH_SOURCE[0]}")/start_review.sh" --demo "$@"
