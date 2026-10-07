}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct FilesystemRequirementsToml {
    pub deny_read: Option<Vec<FilesystemDenyReadPattern>>,
}

#[derive(Deserialize)]
struct RawFilesystemRequirementsToml {
    deny_read: Option<Vec<FilesystemDenyReadPattern>>,
    description: Option<serde::de::IgnoredAny>,
    extends: Option<serde::de::IgnoredAny>,
    workspace_roots: Option<serde::de::IgnoredAny>,
    filesystem: Option<serde::de::IgnoredAny>,
    network: Option<serde::de::IgnoredAny>,
}

impl<'de> Deserialize<'de> for FilesystemRequirementsToml {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawFilesystemRequirementsToml::deserialize(deserializer)?;
        let RawFilesystemRequirementsToml {
            deny_read,
            description,
            extends,
            workspace_roots,
            filesystem,
            network,
        } = raw;

        if description.is_some()
            || extends.is_some()
            || workspace_roots.is_some()
            || filesystem.is_some()
            || network.is_some()
        {
            return Err(D::Error::custom(
                "`permissions.filesystem` is reserved for requirements-level filesystem constraints and cannot define a profile",
            ));
        }

        Ok(Self { deny_read })
    }
}

#[derive(Deserialize, Debug, Clone, Default, PartialEq, Eq)]
pub struct PermissionsRequirementsToml {
    pub filesystem: Option<FilesystemRequirementsToml>,
    // For legacy reasons, `filesystem` stays reserved for requirements-level
    // filesystem constraints and cannot name a profile.
    #[serde(default, flatten)]
    pub profiles: BTreeMap<String, PermissionProfileToml>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FilesystemConstraints {
    pub deny_read: Vec<FilesystemDenyReadPattern>,
}

impl From<PermissionsRequirementsToml> for FilesystemConstraints {
    fn from(value: PermissionsRequirementsToml) -> Self {
        let deny_read = value
            .filesystem
            .and_then(|filesystem| filesystem.deny_read)
            .unwrap_or_default();
        Self { deny_read }
    }
}

