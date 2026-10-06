fn is_permission_allowed(
    allowed_permission_profiles: &BTreeMap<String, bool>,
    profile_id: &str,
) -> bool {
    allowed_permission_profiles
        .get(profile_id)
        .copied()
        .unwrap_or(false)
}
