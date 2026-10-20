# License scope

Robot Skill Hub uses licenses by component and provenance, not one license for every catalog item.

| Component | License | Scope |
| --- | --- | --- |
| Hub API, MCP, discovery CLI, catalog builder, tests and original project documentation | Apache-2.0 | Superfast Robotics' own platform code, under the root LICENSE |
| Hub-authored robotics execution adapters in recipes/ and their templates in tools/recipe_adapters/ | MIT | The separate LICENSE files in those directories; original upstream notices remain applicable |
| Pinned external code, models, policies, data, examples and adapted portions | Their original licenses | Each record's license describes its upstream source, not a blanket license for the Hub wrapper or for unlisted assets |
| External contributions | Applicable component/upstream license and the contributor's authorized grant | Publication permission alone does not establish copyright ownership or permission to relicense |

The machine-readable policy is [license-policy.json](license-policy.json). The original MIT terms remain in [LICENSES/MIT.txt](LICENSES/MIT.txt). Previously published MIT versions retain their original terms. No retroactive license change is asserted.

New platform contributions are submitted under Apache-2.0. Independently authored execution-adapter contributions are submitted under MIT. Changes derived from third-party material must preserve its applicable license, copyright, attribution and required notices. Contributors must have permission to provide their changes under those terms. An upstream license identifier is not a grant for separately licensed model weights, datasets, robot firmware or services.

Prepared projects include the Hub adapter's MIT text and LICENSE_SCOPE.md separately from the immutable upstream checkout's license. Installed discovery clients and connection packages use Apache-2.0; embedded recipe text keeps the MIT exception. No company trademarks are licensed by this policy.
