# cheat sheet for editing plot aesthetics: https://posit.co/wp-content/uploads/2022/10/data-visualization-1.pdf

library(tidyverse)
library(ggbump)
library(ggtext)
library(glue)

theme_colours <- c("#276691", "#1A4242", "#EFB537", "#6C2E3D", "#3B3A78", 
                   "#65A9D6", "#BF687E", "#F5D185", "#68C4C4", "#7A78BE")
extra_colours <- c("#CBE2F1", "#E0F3F3", "#FCEFD6", "#EACCD3", "#D2D1E9")

#### Load and clean data ####
trade_by_industry <- read_csv("fct_trade_by_naics_industry_ranked_yearly.csv") |> 
  filter(!is.na(naics_id)) |>
  select(-c(trading_partner, trade_type)) |>
  rowwise() |>
  mutate(naics_name = ifelse(str_detect(naics_name, "manufacturing"), 
                             yes = str_replace(naics_name, "manufacturing", "mfg."),
                             no = naics_name))

# variables to change for different rankings/countries
#industry_of_interest <- c("1111")
desired_max_rank <- length(theme_colours) #trade_by_industry$naics_id |> unique() |> length()
industry_colour <- data.frame("position" = 1:desired_max_rank, 
                              "plot_colour" = theme_colours)

# alternate mutate for highlighting multiple countries different colours
# mutate(plot_colour = ifelse(naics_id == industry_of_interest[1],
#               yes = "#1A4242",
#               no = ifelse(naics_id == industry_of_interest[2], yes = "#276691", no = "#E7E7E7")))


# add appropriate colours and filter by flow type
#trade_by_industry <- trade_by_industry |> left_join(industry_colour, by = "naics_id") 

imports_to <- trade_by_industry |> filter(trade_direction== "Canada to Japan")
exports_from <- trade_by_industry |> filter(trade_direction== "Japan to Canada")


# standardize years for imports and exports

# 'position' serves as a tie-breaking ranking for plotting
# 'rank' is the true rank (can have ties)

imports_to_naics_id <- imports_to |> arrange(year, cad_value) |>
  group_by(year) |>
  mutate(rank = rank(-cad_value, ties.method = "min")) |>
  mutate(position = rank(-cad_value, ties.method = "random")) 

exports_from_naics_id <- exports_from |> arrange(year, cad_value) |>
  group_by(year) |>
  mutate(rank = rank(-cad_value, ties.method = "min")) |>
  mutate(position = rank(-cad_value, ties.method = "random")) 

first_year_import <- imports_to_naics_id$year |> min()
last_year_import <- imports_to_naics_id$year |> max()

first_year_export <- exports_from_naics_id$year |> min()
last_year_export <- exports_from_naics_id$year |> max()

first_year <- max(first_year_import, first_year_export)
last_year <- min(last_year_import, last_year_export)





#### Imports to naics_id (ie exports from Canada) ####

# filter for chosen years
imports_to_naics_id <- imports_to_naics_id |> 
  filter(year >= first_year & year <= last_year)

# bump plots require 2 or more data points for a industry
# this filters out those with 1 or less
imports_plotting <- imports_to_naics_id |>
  filter(cad_value != 0) |>
  group_by(naics_id) |>
  mutate(years=n())|>
  filter(years>1)

imports_colours <- imports_plotting |> filter(year == last_year) |> select(position, naics_id) |>
  left_join(industry_colour) |> select(-position)

imports_plotting <- left_join(imports_plotting, imports_colours, by = "naics_id") |>
  mutate(plot_colour = ifelse(is.na(plot_colour), "#E7E7E7", plot_colour))

missing_imports <- imports_plotting |> filter(year == 2013 & position <= desired_max_rank & plot_colour == "#E7E7E7") |>
  select(-plot_colour)
missing_imports <- missing_imports |> add_column("plot_colour" = extra_colours[1:dim(missing_imports)[1]])
imports_plotting <- imports_plotting |> mutate(plot_colour = ifelse(naics_id %in% missing_imports$naics_id[1], 
                                                                    yes = missing_imports$plot_colour[1],
                                                                    no = ifelse(naics_id %in% missing_imports$naics_id[2], 
                                                                                yes = missing_imports$plot_colour[2],
                                                                                no = ifelse(naics_id %in% missing_imports$naics_id[3], 
                                                                                            yes = missing_imports$plot_colour[3],
                                                                                            no = plot_colour))))


imports_short <- imports_plotting |> 
  filter((year == 2013 | year == 2023) & position <= 10) |> 
  select(naics_name) |>
  add_column(naics_short_desc = c("Alumina & Alum. Proc & Proc.",
                                  "Logging", 
                                  "Seafood Product Prep. & Pkg.", 
                                  "Non-Ferrous Metal Prod. & Proc. (excl. Alum.)",
                                  "Pulp, Paper & Paperboard Mills", 
                                  "Sawmills & Wood Presv.",
                                  "Meat Product Mfg.",
                                  "Coal Mining",
                                  "Metal Ore Mining",
                                  "Oilseed & Grain Farming",
                                  "Pulp, Paper & Paperboard Mills",
                                  "Other Wood Product Mfg.",
                                  "Sawmills & Wood Presv.",
                                  "Non-Ferrous Metal Prod. & Proc. (excl. Alum.)",
                                  "Pharmaceutical & Medicine Mfg.",
                                  "Petroleum & Coal Product Mfg.",
                                  "Meat Product Mfg.",
                                  "Metal Ore Mining",
                                  "Oilseed & Grain Farming",
                                  "Coal Mining"))

imports_plotting <- left_join(imports_plotting, imports_short, by = c("naics_id", "naics_name"))

# misc. plot variables
label_padding = .2
font_size = '12px'
font_rank_size = '14px'

import_plot <- imports_plotting |>
  ggplot() +
  # make bump plot
  ggbump::geom_bump(mapping=aes(x=year,y=position, group=naics_id, colour = I(plot_colour)), linewidth = 1) +
  # add dots to bump plot
  geom_point(mapping=aes(x=year,y=position, group=naics_id, colour = I(plot_colour)), size = 2) +
  # rank from 1 down
  scale_y_reverse(limits = c(desired_max_rank, NA)) +
  # add labels for first year
  ggtext::geom_richtext(data = imports_plotting|>filter(year==first_year), 
                        hjust=1,
                        mapping=aes(y=position, x=year-label_padding, 
                                    label.size=NA, family="sans",
                                    label=glue("<span style='font-size:{font_size};'>{naics_short_desc}<span style='color:white;'>...</span><span style='font-size:{font_rank_size};'>**{rank}**</span></span>")))+
  # add labels for last year
  ggtext::geom_richtext(data = imports_plotting|>filter(year==last_year), 
                        hjust=0,family="sans",
                        mapping=aes(y=position, x=year+label_padding, 
                                    label.size=NA,
                                    label=glue("<span style='font-size:{font_size};'><span style='font-size:{font_rank_size};'>**{rank}**</span><span style='color:white;'>...</span>{naics_short_desc}</span>")))+
  #add breathing room in x axis to account for labels, change breaks to years
  scale_x_continuous(limits=c(first_year - 5.75, last_year + 6), 
                     breaks = seq(from = first_year, to = last_year, by = 2)) +
  theme_minimal()+
  theme(text=element_text(family="sans"), 
        plot.title = element_text(size=14, hjust = 0.5),
        axis.text.x=element_text(size=10, vjust=5),
        axis.ticks=element_blank(),
        axis.text.y=element_blank(),
        panel.background = element_blank(),
        panel.grid = element_blank()) +
  labs(title="Ranking of Top 10 Industries for Exports from Canada to Japan")+
  xlab("Year") +
  ylab("")

import_plot

# save image to port into decks etc., done this way to ensure standard ratios
#ggsave("imports_to_naics_id_bump_plot.png", import_plot, bg = 'white', height = 8, width = 10.5, units = "in")





#### Exports to naics_id (ie imports from Canada) ####

# filter on chosen years
exports_from_naics_id <- exports_from_naics_id |> 
  filter(year >= first_year & year <= last_year)

# bump plots require 2 or more data points for a industry
# this filters out those with 1 or less
exports_plotting <- exports_from_naics_id |>
  group_by(naics_id) |>
  mutate(years=n())|>
  filter(years>1)

theme_colours <- c("#276691", "#1A4242", "#EFB537", "#6C2E3D", "#3B3A78", 
                   "#65A9D6", "#BF687E", "#68C4C4", "#F5D185", "#7A78BE")
extra_colours <- c("#CBE2F1", "#E0F3F3", "#FCEFD6", "#EACCD3", "#D2D1E9")


industry_colour <- data.frame("position" = 1:desired_max_rank, 
                              "plot_colour" = theme_colours)

exports_colours <- exports_plotting |> filter(year == last_year) |> select(position, naics_id) |>
  left_join(industry_colour) |> select(-position)

exports_plotting <- left_join(exports_plotting, exports_colours, by = "naics_id") |>
  mutate(plot_colour = ifelse(is.na(plot_colour), "#E7E7E7", plot_colour))

missing_exports <- exports_plotting |> filter(year == 2013 & position <= desired_max_rank & plot_colour == "#E7E7E7") |>
  select(-plot_colour)
missing_exports <- missing_exports |> add_column("plot_colour" = extra_colours[1:dim(missing_exports)[1]])
exports_plotting <- exports_plotting |> mutate(plot_colour = ifelse(naics_id %in% missing_exports$naics_id[1], 
                                                                    yes = missing_exports$plot_colour[1],
                                                                    no = ifelse(naics_id %in% missing_exports$naics_id[2], 
                                                                                yes = missing_exports$plot_colour[2],
                                                                                no = ifelse(naics_id %in% missing_exports$naics_id[3], 
                                                                                            yes = missing_exports$plot_colour[3],
                                                                                            no = plot_colour))))
exports_short <- exports_plotting |> 
  filter((year == 2013 | year == 2023) & position <= 10) |> 
  select(naics_name) |>
  add_column(naics_short_desc = c("Comp. & Peripheral Eqpt. Mfg.",
               "Semiconductor & Elec. Component Mfg.", 
               "Nav., Measuring, Medical & Control Instr. Mfg.", 
               "Rubber Prod. Mfg.", 
               "Aerospace Prod. & Parts Mfg.", 
               "Other General-Purpose Mach. Mfg.",
               "Indust. Mach. Mfg.",
               "Agri., Constr. & Mining Mach. Mfg.",
               "Motor Vehicle Parts Mfg.",
               "Motor Vehicle Mfg.",
               "Indust. Mach. Mfg.",
               "Nav., Measuring, Medical & Control Instr. Mfg.", 
               "Non-Ferrous Metal Prod. & Proc. (excl. Alum.)",
               "Rubber Prod. Mfg.", 
               "Other General-Purpose Mach. Mfg.",
               "Other Elec. Eqpt. & Component Mfg.",
               "Engine, Turbine & Power Transm. Eqpt. Mfg.",
               "Motor Vehicle Parts Mfg.",
               "Agri., Constr. & Mining Mach. Mfg.",
               "Motor Vehicle Mfg."))

exports_plotting <- left_join(exports_plotting, exports_short, by = c("naics_id", "naics_name"))
# misc. plot variables
label_padding = .2
font_size = '12px'
font_rank_size = '14px'

export_plot <- exports_plotting |>
  ggplot() +
  # make bump plot
  ggbump::geom_bump(mapping=aes(x=year,y=position, group=naics_id, colour = I(plot_colour)), linewidth = 1) +
  # add dots to bump plot
  geom_point(mapping=aes(x=year,y=position, group=naics_id, colour = I(plot_colour)), size = 2) +
  # rank from 1 down
  scale_y_reverse(limits = c(desired_max_rank, NA)) +
  # add labels for first year
  ggtext::geom_richtext(data = exports_plotting|>filter(year==first_year), 
                        hjust=1,
                        mapping=aes(y=position, x=year-label_padding, 
                                    label.size=NA, family="sans",
                                    label=glue("<span style='font-size:{font_size};'>{naics_short_desc}<span style='color:white;'>...</span><span style='font-size:{font_rank_size};'>**{rank}**</span></span>")))+
  # add labels for last year
  ggtext::geom_richtext(data = exports_plotting|>filter(year==last_year), 
                        hjust=0,family="sans",
                        mapping=aes(y=position, x=year+label_padding, 
                                    label.size=NA,
                                    label=glue("<span style='font-size:{font_size};'><span style='font-size:{font_rank_size};'>**{rank}**</span><span style='color:white;'>...</span>{naics_short_desc}</span>")))+
  #add breathing room in x axis to account for labels, change breaks to years
  scale_x_continuous(limits=c(first_year - 5.75, last_year + 6), 
                     breaks = seq(from = first_year, to = last_year, by = 2)) +
  theme_minimal()+
  theme(text=element_text(family="sans"), 
        plot.title = element_text(size=14, hjust = 0.5),
        axis.text.x=element_text(size=10, vjust=5),
        axis.ticks=element_blank(),
        axis.text.y=element_blank(),
        panel.background = element_blank(),
        panel.grid = element_blank()) +
  labs(title="Ranking of Top 10 Industries for Exports from Japan to Canada")+
  xlab("Year") +
  ylab("")

export_plot


# save image to port into decks etc., done this way to ensure standard ratios
#ggsave("exports_from_naics_id_bump_plot.png", export_plot, bg = 'white', height = 8, width = 10.5, units = "in")

