# Load required libraries
library(shiny)
library(shinydashboard)
library(DT)
library(readxl)
library(dplyr)
library(ggplot2)
library(plotly)
library(tidyr)

# UI definition
ui <- dashboardPage(
  dashboardHeader(title = "Torah Data Explorer"),
  
  dashboardSidebar(
    sidebarMenu(
      menuItem("Data Overview", tabName = "overview", icon = icon("table")),
      menuItem("Data Tables", tabName = "tables", icon = icon("database")),
      menuItem("Charts", tabName = "charts", icon = icon("bar-chart")),
      menuItem("About", tabName = "about", icon = icon("info-circle"))
    )
  ),
  
  dashboardBody(
    tabItems(
      # Overview tab
      tabItem(tabName = "overview",
        fluidRow(
          box(
            title = "Data File Information",
            status = "primary",
            solidHeader = TRUE,
            width = 12,
            verbatimTextOutput("file_info")
          )
        ),
        fluidRow(
          box(
            title = "Sheet Selection",
            status = "info",
            solidHeader = TRUE,
            width = 6,
            selectInput("sheet_select", "Choose a sheet:", choices = NULL),
            actionButton("load_sheet", "Load Sheet", class = "btn-primary")
          ),
          box(
            title = "Current Sheet Info",
            status = "success",
            solidHeader = TRUE,
            width = 6,
            verbatimTextOutput("sheet_info")
          )
        )
      ),
      
      # Tables tab
      tabItem(tabName = "tables",
        fluidRow(
          box(
            title = "Data Table",
            status = "primary",
            solidHeader = TRUE,
            width = 12,
            DTOutput("data_table")
          )
        )
      ),
      
      # Charts tab
      tabItem(tabName = "charts",
        fluidRow(
          box(
            title = "Chart Controls",
            status = "warning",
            solidHeader = TRUE,
            width = 4,
            selectInput("chart_type", "Chart Type:", 
                       choices = c("Bar Chart", "Line Chart", "Scatter Plot", "Histogram", "Box Plot")),
            uiOutput("x_axis_selector"),
            uiOutput("y_axis_selector"),
            uiOutput("color_selector"),
            uiOutput("facet_selector"),
            uiOutput("filter_controls"),
            actionButton("update_chart", "Update Chart", class = "btn-success")
          ),
          box(
            title = "Chart Output",
            status = "primary",
            solidHeader = TRUE,
            width = 8,
            plotlyOutput("chart_output", height = "500px")
          )
        )
      ),
      
      # About tab
      tabItem(tabName = "about",
        fluidRow(
          box(
            title = "About This App",
            status = "info",
            solidHeader = TRUE,
            width = 12,
            p("This R Shiny application allows you to explore and visualize data from the Data.xlsx file."),
            p("Features include:"),
            tags$ul(
              tags$li("Browse different sheets within the Excel file"),
              tags$li("Interactive data tables with sorting and filtering"),
              tags$li("Dynamic chart creation with various visualization options"),
              tags$li("Column-based filtering and selection")
            ),
            p("Built with Shiny Dashboard for a clean, professional interface.")
          )
        )
      )
    )
  )
)

# Server logic
server <- function(input, output, session) {
  
  # Reactive values to store data
  rv <- reactiveValues(
    data = NULL,
    current_sheet = NULL,
    sheet_names = NULL
  )
  
  # Initialize by reading the Excel file
  observe({
    tryCatch({
      # Get sheet names
      rv$sheet_names <- excel_sheets("Data.xlsx")
      updateSelectInput(session, "sheet_select", choices = rv$sheet_names)
      
      # Display file info
      output$file_info <- renderText({
        paste("File: Data.xlsx\n",
              "Number of sheets:", length(rv$sheet_names), "\n",
              "Available sheets:", paste(rv$sheet_names, collapse = ", "))
      })
    }, error = function(e) {
      output$file_info <- renderText({
        paste("Error reading file:", e$message)
      })
    })
  })
  
  # Load selected sheet
  observeEvent(input$load_sheet, {
    if (!is.null(input$sheet_select)) {
      tryCatch({
        rv$data <- read_excel("Data.xlsx", sheet = input$sheet_select)
        rv$current_sheet <- input$sheet_select
        
        # Update sheet info
        output$sheet_info <- renderText({
          paste("Current sheet:", rv$current_sheet, "\n",
                "Rows:", nrow(rv$data), "\n",
                "Columns:", ncol(rv$data), "\n",
                "Column names:", paste(names(rv$data), collapse = ", "))
        })
      }, error = function(e) {
        output$sheet_info <- renderText({
          paste("Error loading sheet:", e$message)
        })
      })
    }
  })
  
  # Data table output
  output$data_table <- renderDT({
    if (!is.null(rv$data)) {
      datatable(rv$data, 
                options = list(pageLength = 25, scrollX = TRUE),
                filter = "top",
                selection = "single")
    }
  })
  
  # Dynamic UI for chart controls
  output$x_axis_selector <- renderUI({
    if (!is.null(rv$data)) {
      selectInput("x_axis", "X-Axis Variable:", choices = names(rv$data))
    }
  })
  
  output$y_axis_selector <- renderUI({
    if (!is.null(rv$data)) {
      selectInput("y_axis", "Y-Axis Variable:", choices = names(rv$data))
    }
  })
  
  output$color_selector <- renderUI({
    if (!is.null(rv$data)) {
      selectInput("color_var", "Color Variable (optional):", 
                  choices = c("None", names(rv$data)))
    }
  })
  
  output$facet_selector <- renderUI({
    if (!is.null(rv$data)) {
      selectInput("facet_var", "Facet Variable (optional):", 
                  choices = c("None", names(rv$data)))
    }
  })
  
  # Filter controls for boolean columns
  output$filter_controls <- renderUI({
    if (!is.null(rv$data)) {
      # Find boolean/logical columns
      bool_cols <- names(rv$data)[sapply(rv$data, function(x) {
        is.logical(x) || (is.character(x) && all(unique(x) %in% c("TRUE", "FALSE", "True", "False", "true", "false", "", NA)))
      })]
      
      if (length(bool_cols) > 0) {
        tagList(
          h4("Boolean Filters:"),
          lapply(bool_cols, function(col) {
            checkboxGroupInput(
              inputId = paste0("filter_", col),
              label = col,
              choices = c("TRUE", "FALSE"),
              selected = c("TRUE", "FALSE")
            )
          })
        )
      } else {
        p("No boolean columns found for filtering.")
      }
    }
  })
  
  # Chart output
  output$chart_output <- renderPlotly({
    if (!is.null(rv$data) && !is.null(input$x_axis) && !is.null(input$y_axis)) {
      
      # Apply boolean filters
      filtered_data <- rv$data
      if (!is.null(input$filter_controls)) {
        bool_cols <- names(rv$data)[sapply(rv$data, function(x) {
          is.logical(x) || (is.character(x) && all(unique(x) %in% c("TRUE", "FALSE", "True", "False", "true", "false", "", NA)))
        })]
        
        for (col in bool_cols) {
          filter_input <- input[[paste0("filter_", col)]]
          if (!is.null(filter_input) && length(filter_input) > 0) {
            # Convert to logical for filtering
            col_data <- as.character(filtered_data[[col]])
            filtered_data <- filtered_data[col_data %in% filter_input, ]
          }
        }
      }
      
      # Create plot based on chart type
      p <- switch(input$chart_type,
        "Bar Chart" = {
          if (input$color_var != "None") {
            ggplot(filtered_data, aes_string(x = input$x_axis, y = input$y_axis, fill = input$color_var)) +
              geom_bar(stat = "identity") +
              theme_minimal() +
              labs(title = paste("Bar Chart:", input$y_axis, "by", input$x_axis))
          } else {
            ggplot(filtered_data, aes_string(x = input$x_axis, y = input$y_axis)) +
              geom_bar(stat = "identity", fill = "steelblue") +
              theme_minimal() +
              labs(title = paste("Bar Chart:", input$y_axis, "by", input$x_axis))
          }
        },
        "Line Chart" = {
          if (input$color_var != "None") {
            ggplot(filtered_data, aes_string(x = input$x_axis, y = input$y_axis, color = input$color_var)) +
              geom_line() +
              theme_minimal() +
              labs(title = paste("Line Chart:", input$y_axis, "by", input$x_axis))
          } else {
            ggplot(filtered_data, aes_string(x = input$x_axis, y = input$y_axis)) +
              geom_line(color = "steelblue") +
              theme_minimal() +
              labs(title = paste("Line Chart:", input$y_axis, "by", input$x_axis))
          }
        },
        "Scatter Plot" = {
          if (input$color_var != "None") {
            ggplot(filtered_data, aes_string(x = input$x_axis, y = input$y_axis, color = input$color_var)) +
              geom_point() +
              theme_minimal() +
              labs(title = paste("Scatter Plot:", input$y_axis, "vs", input$x_axis))
          } else {
            ggplot(filtered_data, aes_string(x = input$x_axis, y = input$y_axis)) +
              geom_point(color = "steelblue") +
              theme_minimal() +
              labs(title = paste("Scatter Plot:", input$y_axis, "vs", input$x_axis))
          }
        },
        "Histogram" = {
          ggplot(filtered_data, aes_string(x = input$x_axis)) +
            geom_histogram(fill = "steelblue", alpha = 0.7) +
            theme_minimal() +
            labs(title = paste("Histogram of", input$x_axis))
        },
        "Box Plot" = {
          if (input$color_var != "None") {
            ggplot(filtered_data, aes_string(x = input$color_var, y = input$y_axis)) +
              geom_boxplot() +
              theme_minimal() +
              labs(title = paste("Box Plot:", input$y_axis, "by", input$color_var))
          } else {
            ggplot(filtered_data, aes_string(y = input$y_axis)) +
              geom_boxplot(fill = "steelblue") +
              theme_minimal() +
              labs(title = paste("Box Plot of", input$y_axis))
          }
        }
      )
      
      # Add faceting if selected
      if (!is.null(input$facet_var) && input$facet_var != "None") {
        p <- p + facet_wrap(as.formula(paste("~", input$facet_var)))
      }
      
      # Convert to plotly
      ggplotly(p)
    }
  })
}

# Run the app
shinyApp(ui = ui, server = server) 