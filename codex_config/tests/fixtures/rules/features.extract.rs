    FeatureSpec {
        id: Feature::CodexHooks,
        key: "hooks",
        stage: Stage::Stable,
        default_enabled: true,
    },

    FeatureSpec {
        id: Feature::NetworkProxy,
        key: "network_proxy",
        stage: Stage::Experimental {
            name: "Network proxy",
            menu_description: "Apply network proxy restrictions to sandboxed sessions that already have network access.",
            announcement: "NEW: Network proxy can now be enabled from /experimental. Restart Codex after enabling it.",
        },
        default_enabled: false,
