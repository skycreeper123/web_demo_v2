This is a legacy workflow-manifest folder.

The application now scans the configured `workflow_manifest_dir`, which defaults to the project-root `workflow/` directory. Put production workflow templates there so the ComfyUI UI can discover them automatically. The default project templates are maintained only in `workflow/`; do not keep duplicate copies here.

This folder can still be selected explicitly by setting `workflow_manifest_dir` in `backend/comfyui_comm_config.json`, but that is not the default recommendation.

Expected manifest format:

```json
{
  "key": "image_video_to_video_prod",
  "label": "Image + Video to Video",
  "workflow_type": "image_video_to_video",
  "description": "Production workflow exported in API format.",
  "workflow": {
    "...": "ComfyUI API workflow JSON"
  },
  "bindings": {
    "positive_prompt": [{ "node": "10", "input": "text", "required": true }],
    "negative_prompt": [{ "node": "11", "input": "text" }],
    "image_ref": [{ "node": "12", "input": "image" }],
    "video_ref": [{ "node": "13", "input": "file" }],
    "seed": [{ "node": "20", "input": "seed", "type": "int" }],
    "output_prefix": [{ "node": "99", "input": "filename_prefix", "required": true }],
    "params.steps": [{ "node": "25", "input": "steps", "type": "int" }],
    "params.cfg": [{ "node": "25", "input": "cfg", "type": "float" }]
  }
}
```

For a raw ComfyUI API workflow JSON, the app can infer common bindings as a first draft. Verify the result, then save explicit bindings in the manifest before using the workflow for batch production.

If the configured manifest folder is empty, the app can still run by pasting inline workflow JSON and bindings JSON in the ComfyUI module UI.
