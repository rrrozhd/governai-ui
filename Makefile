.PHONY: release update-formula

release:
	./scripts/release.sh "$(VERSION)"

update-formula:
	./scripts/update_formula.sh
