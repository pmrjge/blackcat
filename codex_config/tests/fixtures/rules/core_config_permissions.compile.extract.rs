fn compile_filesystem_permission(
    path: &str,
    permission: &FilesystemPermissionToml,
    context: &ConfigPathContext,
    startup_warnings: &mut Vec<String>,
) -> io::Result<Vec<FileSystemSandboxEntry>> {
    let mut entries = Vec::new();
    match permission {
        FilesystemPermissionToml::Access(access) => {
            entries.push(FileSystemSandboxEntry {
                path: compile_filesystem_access_path(path, *access, context, startup_warnings)?,
                access: *access,
                missing_path_behavior: None,
            });
        }
        FilesystemPermissionToml::Scoped(scoped_entries) => {
            for (subpath, access) in scoped_entries {
                if matches!(
                    parse_special_path(path),
                    Some(FileSystemSpecialPath::ProjectRoots { .. })
                ) && context.convention().home_relative_suffix(subpath).is_some()
                {
                    permission_path::relative_subpath(subpath, context)?;
                    entries.push(FileSystemSandboxEntry {
                        path: compile_filesystem_access_path(
                            subpath,
                            *access,
                            context,
                            startup_warnings,
                        )?,
                        access: *access,
                        missing_path_behavior: None,
                    });
                    continue;
                }
                let has_glob = permission_path::contains_glob(subpath, context)?;
                let can_compile_as_pattern = match parse_special_path(path) {
                    Some(FileSystemSpecialPath::ProjectRoots { .. }) | None => true,
                    Some(_) => false,
                };
                if has_glob && *access == FileSystemAccessMode::Deny && can_compile_as_pattern {
                    // Scoped glob syntax is a first-class filesystem policy
                    // pattern entry. Literal scoped paths continue through the
                    // exact-path parser so existing path semantics stay intact.
                    let entry = FileSystemSandboxEntry {
                        path: FileSystemPath::GlobPattern {
                            pattern: compile_scoped_filesystem_pattern(
                                path, subpath, *access, context,
                            )?,
                        },
                        access: *access,
                        missing_path_behavior: None,
                    };
                    entries.push(entry);
                } else {
                    let subpath = compile_read_write_glob_path(subpath, *access, context)?;
                    entries.push(FileSystemSandboxEntry {
                        path: compile_scoped_filesystem_path(
                            path,
                            subpath,
                            context,
                            startup_warnings,
                        )?,
                        access: *access,
                        missing_path_behavior: None,
                    });
                }
            }
        }
    }
    Ok(entries)
}

fn compile_filesystem_access_path(
    path: &str,
    access: FileSystemAccessMode,
    context: &ConfigPathContext,
    startup_warnings: &mut Vec<String>,
) -> io::Result<FileSystemPath> {
    if !permission_path::contains_glob(path, context)? {
        return compile_filesystem_path(path, context, startup_warnings);
    }

    if access == FileSystemAccessMode::Deny {
        // At this point `path` is an unscoped filesystem table key. Top-level
        // glob deny entries still go through the absolute-path parser before
        // becoming policy patterns; relative project-root glob syntax is
        // handled by `compile_scoped_filesystem_pattern`.
        return Ok(FileSystemPath::GlobPattern {
            pattern: permission_path::absolute_path(path, context)?
                .to_config_path_string(context.convention())
                .map_err(|err| io::Error::new(io::ErrorKind::InvalidInput, err))?,
        });
    }

    let path = compile_read_write_glob_path(path, access, context)?;
    compile_filesystem_path(path, context, startup_warnings)
}

fn compile_filesystem_path(
    path: &str,
    context: &ConfigPathContext,
    startup_warnings: &mut Vec<String>,
) -> io::Result<FileSystemPath> {
    if let Some(special) = parse_special_path(path) {
        maybe_push_unknown_special_path_warning(&special, startup_warnings);
        return Ok(FileSystemPath::Special { value: special });
    }

    Ok(permission_path::absolute_path(path, context)?.into())
}

fn compile_scoped_filesystem_path(
    path: &str,
    subpath: &str,
    context: &ConfigPathContext,
    startup_warnings: &mut Vec<String>,
) -> io::Result<FileSystemPath> {
    if subpath == "." {
        return compile_filesystem_path(path, context, startup_warnings);
    }

    if let Some(special) = parse_special_path(path) {
        let subpath = permission_path::relative_subpath(subpath, context)?;
        let special = match special {
            FileSystemSpecialPath::ProjectRoots { .. } => Ok(FileSystemPath::Special {
                value: FileSystemSpecialPath::project_roots(Some(subpath)),
            }),
            FileSystemSpecialPath::Unknown { path, .. } => Ok(FileSystemPath::Special {
                value: FileSystemSpecialPath::unknown(path, Some(subpath)),
            }),
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("filesystem path `{path}` does not support nested entries"),
            )),
        }?;
        if let FileSystemPath::Special { value } = &special {
            maybe_push_unknown_special_path_warning(value, startup_warnings);
        }
        return Ok(special);
    }

    let subpath = permission_path::relative_subpath(subpath, context)?;
    let base = permission_path::absolute_path(path, context)?;
    let path = context
        .resolve_against(&subpath, &base)
        .map_err(|err| io::Error::new(io::ErrorKind::InvalidInput, err))?;
    Ok(path.into())
}

fn compile_scoped_filesystem_pattern(
    path: &str,
    subpath: &str,
    access: FileSystemAccessMode,
    context: &ConfigPathContext,
) -> io::Result<String> {
    // Pattern entries currently mean deny-read only. Supporting broader access
    // modes here would imply glob-based read/write allow semantics that the
    // sandbox policy does not express yet.
    if access != FileSystemAccessMode::Deny {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("filesystem glob subpath `{subpath}` only supports `deny` access"),
        ));
    }
    let subpath = permission_path::relative_subpath(subpath, context)?;

    match parse_special_path(path) {
        Some(FileSystemSpecialPath::ProjectRoots { .. }) => {
            // Keep `:workspace_roots` glob patterns symbolic until the active
            // workspace roots are known, then materialize them for cwd and any
            // runtime/profile-added workspace roots together.
            Ok(project_roots_glob_pattern(Path::new(&subpath)))
        }
        Some(_) => Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("filesystem path `{path}` does not support nested entries"),
        )),
        None => {
            let base = permission_path::absolute_path(path, context)?;
            context
                .resolve_against(&subpath, &base)
                .and_then(|path| path.to_config_path_string(context.convention()))
                .map_err(|err| io::Error::new(io::ErrorKind::InvalidInput, err))
        }
    }
}

fn compile_read_write_glob_path<'a>(
    path: &'a str,
    access: FileSystemAccessMode,
    context: &ConfigPathContext,
) -> io::Result<&'a str> {
    if !permission_path::contains_glob(path, context)? {
        return Ok(path);
    }

    let path_without_trailing_glob = remove_trailing_glob_suffix(path);
    if !permission_path::contains_glob(path_without_trailing_glob, context)? {
        return Ok(path_without_trailing_glob);
    }

    Err(io::Error::new(
        io::ErrorKind::InvalidInput,
        format!(
            "filesystem glob path `{path}` only supports `deny` access; use an exact path or trailing `/**` for `{access}` subtree access"
        ),
    ))
}

fn unsupported_read_write_glob_paths(
    filesystem: &FilesystemPermissionsToml,
    context: &ConfigPathContext,
) -> io::Result<Vec<String>> {
    let mut patterns = Vec::new();
    for (path, permission) in &filesystem.entries {
        match permission {
            FilesystemPermissionToml::Access(access) => {
                if *access != FileSystemAccessMode::Deny
                    && permission_path::contains_glob(remove_trailing_glob_suffix(path), context)?
                {
                    patterns.push(path.clone());
                }
            }
            FilesystemPermissionToml::Scoped(scoped_entries) => {
                for (subpath, access) in scoped_entries {
                    if *access != FileSystemAccessMode::Deny
                        && permission_path::contains_glob(
                            remove_trailing_glob_suffix(subpath),
                            context,
                        )?
                    {
                        patterns.push(format!("{path}/{subpath}"));
                    }
                }
            }
        }
    }
    Ok(patterns)
}

fn unbounded_unreadable_globstar_paths(filesystem: &FilesystemPermissionsToml) -> Vec<String> {
    if filesystem.glob_scan_max_depth.is_some() {
        return Vec::new();
