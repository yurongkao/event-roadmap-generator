import streamlit as st
import pandas as pd
import json
from datetime import date
from src.engine import generate_roadmap_rows
from src.ai_helper import generate_task_json, generate_task_checklist

if "roadmap_df" not in st.session_state:
    st.session_state["roadmap_df"] = None  # 儲存最新可用的 roadmap dataframe
if "has_roadmap" not in st.session_state:
    st.session_state["has_roadmap"] = False

st.set_page_config(page_title="Event Roadmap Generator", layout="wide")
st.title("📅 Event Roadmap Generator")

if "roadmap_df" not in st.session_state:
    st.session_state["roadmap_df"] = None
if "task_templates" not in st.session_state:
    st.session_state["task_templates"] = None
if "ai_checklists" not in st.session_state:
    st.session_state["ai_checklists"] = {}


# Sidebar input
st.sidebar.header("Inputs")
st.sidebar.markdown("---")
st.sidebar.subheader("🤖 AI Helper: Add a Task")

ai_text = st.sidebar.text_area(
    "Describe a task in one sentence",
    placeholder="e.g., Early bird registration starts 8 weeks before event and lasts 3 weeks (Event Execution).",
)

if "ai_new_task" not in st.session_state:
    st.session_state["ai_new_task"] = None

event_date = st.sidebar.date_input("Event Date")
director_start_date = st.sidebar.date_input("Director Start Date")

uploaded_file = st.sidebar.file_uploader(
    "Upload task template (task.json)",
    type=["json"]
)

prev_csv = st.sidebar.file_uploader(
    "Optional: Upload previous roadmap.csv (to keep Status)",
    type=["csv"]
)

clamp = st.sidebar.checkbox(
    "Clamp tasks to director start date",
    value=True
)

# Main area
if uploaded_file and event_date and director_start_date:
    st.session_state["task_templates"] = json.load(uploaded_file)

    # 方便後面使用
    task_templates = st.session_state["task_templates"]


    if st.button("Generate Roadmap"):
        rows = generate_roadmap_rows(
            task_templates,
            event_date,
            director_start_date,
            clamp=clamp
        )

        df = pd.DataFrame(rows)
        st.session_state["roadmap_df"] = df.copy()
        st.session_state["has_roadmap"] = True  
        # Keep Status from previous roadmap
        # ---- Step 4: Keep Status from previous roadmap ----
        prev_df = None

        if prev_csv is not None:
            try:
                prev_df = pd.read_csv(prev_csv)
            except Exception as e:
                st.sidebar.error(f"Failed to read previous CSV: {e}")
                prev_df = None  

        if prev_df is not None:
            required_cols = {"Task", "Project", "Status"}

            if required_cols.issubset(set(prev_df.columns)):
                status_map = (
                    prev_df.dropna(subset=["Task", "Project", "Status"])
                        .set_index(["Task", "Project"])["Status"]
                        .to_dict()
                )

                df["Status"] = df.apply(
                    lambda row: status_map.get((row["Task"], row["Project"]), row["Status"]),
                    axis=1
                )
                st.sidebar.success("Loaded previous Status ✔")
            else:
                st.sidebar.warning(
                    "Previous CSV missing required columns (Task, Project, Status). Skipped."
                )
        # 按 Generate Roadmap 時，把「生成好的 df」存起來
        st.session_state["roadmap_df"] = df.copy()

    
    if st.session_state["has_roadmap"] and st.session_state["roadmap_df"] is not None:
        df = st.session_state["roadmap_df"].copy()
        
        st.subheader("Roadmap Preview")

        # Filter
        all_projects = sorted(df["Project"].unique().tolist())
        selected_projects = st.multiselect(
            "Filter by Project",
            options=all_projects,
            default=all_projects,
        )

        df_view = df[df["Project"].isin(selected_projects)].copy()
        
        #Sort
        sort_option = st.selectbox(
            "Sort by",
            ["Start Date", "Project + Start Date", "Task"],
        )

        if sort_option == "Start Date":
            df_view = df_view.sort_values(["Start Date", "Project", "Task"])
        elif sort_option == "Project + Start Date":
            df_view = df_view.sort_values(["Project", "Start Date", "Task"])
        else:
            df_view = df_view.sort_values(["Task", "Project", "Start Date"])

        #Editable Status
        edited_df = st.data_editor(
            df_view,
            column_config={
            "Status": st.column_config.SelectboxColumn(
            "Status",
            options=["Not Started", "In Progress", "Done"],
            required=True,
                )   
            },
            use_container_width=True,
            hide_index=True,
            key="roadmap_editor" 
        )

        st.session_state["roadmap_df"] = edited_df
        st.session_state["has_roadmap"] = True

        csv_bytes = edited_df.to_csv(index=False).encode("utf-8")
        
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name="roadmap.csv",
            mime="text/csv",
        )
    
        # 加一個「AI Checklist」區塊
        st.markdown("---")
        st.subheader("🤖 AI Helper: Checklist for a Task")

        df_for_ai = edited_df.copy()

        df_for_ai["__key"] = df_for_ai["Task"].astype(str) + " | " + df_for_ai["Project"].astype(str)
        options = df_for_ai["__key"].tolist()

        selected_key = st.selectbox("Select a task", options)
        selected_row = df_for_ai[df_for_ai["__key"] == selected_key].iloc[0]

        cache_key = selected_key + f"::{selected_row['Start Date']}::{selected_row['End Date']}"

        colA, colB = st.columns([1, 1], vertical_alignment="top")

        with colA:
            st.write("## Selected task")
            st.write(f"**Task:** {selected_row['Task']}")
            st.write(f"**Project:** {selected_row['Project']}")
            st.write(f"**Status:** {selected_row['Status']}")
            st.write(f"**Dates:** {selected_row['Start Date']} → {selected_row['End Date']}")

            if st.button("Generate Checklist", key="btn_checklist"):
                with st.spinner("Generating checklist..."):
                    try:
                        result = generate_task_checklist(
                            task_name=str(selected_row["Task"]),
                            project=str(selected_row["Project"]),
                            start_date=str(selected_row["Start Date"]),
                            end_date=str(selected_row["End Date"]),
                            status=str(selected_row["Status"]),
                            context_projects=sorted(df_for_ai["Project"].unique().tolist()),
                        )
                        st.session_state["ai_checklists"][cache_key] = result
                        st.success("Generated ✅")
                    except Exception as e:
                        st.error(f"Checklist generation failed: {e}")

        with colB:
            st.write("## AI Output")

            out = st.session_state["ai_checklists"].get(cache_key)

            if out is None:
                st.info("Select a task and click **Generate Checklist**.")
            else:
                st.write("### Done definition")
                st.write(out.get("done_definition", ""))

                st.write("### Checklist")
                for item in out.get("checklist", []):
                    st.checkbox(item, key=f"chk::{cache_key}::{item}")

                st.write("### Risks")
                for r in out.get("risks", []):
                    st.write(f"- {r}")
else:
    st.info("Please upload a task template and select dates.")

def compute_next_task_id(task_templates: list[dict]) -> str:
    nums = []
    for t in task_templates:
        tid = t.get("task_id")
        if isinstance(tid, str) and tid.startswith("T") and tid[1:].isdigit():
            nums.append(int(tid[1:]))
    nxt = (max(nums) + 1) if nums else 1
    return f"T{nxt:02d}"

# 按鈕：呼叫 LLM → 產 JSON
task_templates = st.session_state.get("task_templates")
if task_templates is None:
    st.sidebar.info("Upload task.json first to use AI Helper.")
if task_templates is not None and st.sidebar.button("Generate Task JSON"):
    if not ai_text.strip():
        st.sidebar.warning("Please enter a task description.")
    else:
        next_id = compute_next_task_id(task_templates)
        existing_projects = [t.get("project", "") for t in task_templates if isinstance(t.get("project", ""), str)]
        existing_titles = [t.get("task", "") for t in task_templates if isinstance(t.get("task", ""), str)]
        existing_ids = [t.get("task_id", "") for t in task_templates if isinstance(t.get("task_id", ""), str)]

        try:
            new_task = generate_task_json(
                user_text=ai_text,
                next_task_id=next_id,
                existing_projects=existing_projects,
                existing_task_titles=existing_titles,
                existing_task_ids=existing_ids,
            )
            st.session_state["ai_new_task"] = new_task
            st.sidebar.success("Generated! Review the JSON below.")
        except Exception as e:
            st.sidebar.error(f"AI generation failed: {e}")
            st.session_state["ai_new_task"] = None

# 顯示 JSON + “Add to Template” 按鈕
if st.session_state["ai_new_task"] is not None:
    st.sidebar.write("Review:")
    st.sidebar.json(st.session_state["ai_new_task"])

    if st.sidebar.button("Add to Template"):
        # Guardrails: validate via engine before committing
        try:
            candidate = task_templates + [st.session_state["ai_new_task"]]

            # 用你 engine 的 loader/validator 確保 schema OK
            # （你 engine 應該有 load_templates_from_obj + validate_templates）
            from src.engine import load_templates_from_obj, validate_templates

            templates_obj = load_templates_from_obj(candidate)
            validate_templates(templates_obj)

            task_templates.append(st.session_state["ai_new_task"])
            st.session_state["ai_new_task"] = None
            st.sidebar.success("Added! Now click Generate Roadmap.")
        except Exception as e:
            st.sidebar.error(f"Cannot add task (failed validation): {e}")
