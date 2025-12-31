# cheat sheet for editing plot aesthetics: https://posit.co/wp-content/uploads/2022/10/data-visualization-1.pdf

library(tidyverse)
library(ggbump)
library(ggtext)
library(glue)

#### Load and clean data ####
trade_by_country <- read_csv("fct_fdi_ultimate_yearly.csv") |> 
  select(-m49_code, -sccai_code) |> distinct()


#### FDI ####

# variables to change for different rankings/countries
country_of_interest <- c("Japan")
desired_max_rank <- 16
country_colour <- data.frame("region" = trade_by_country$region |> unique()) |>
  mutate(plot_colour = ifelse(region == country_of_interest[1], yes = "#1A4242", no = "#E7E7E7"))

# alternate mutate for highlighting multiple countries different colours
# mutate(plot_colour = ifelse(region == country_of_interest[1],
#               yes = "#1A4242",
#               no = ifelse(region == country_of_interest[2], yes = "#276691", no = "#E7E7E7")))


# Remove 'All countries' rows
trade_by_country <- subset(trade_by_country, region != "All countries")


# filter by flow type
trade_by_country <- trade_by_country |> left_join(country_colour, by = "region")

cdi <- trade_by_country |> filter(fdi_type== "Canadian direct investment abroad by ultimate investor country - total book value")
fdi <- trade_by_country |> filter(fdi_type== "Foreign direct investment in Canada by ultimate investor country - total book value")


# standardize years for cdi and fdi

cdi_region <- cdi |> arrange(year, dollar_value) |>
  group_by(year) |>
  mutate(rank = rank(-dollar_value, ties.method = "min")) |>
  mutate(position = rank(-dollar_value, ties.method = "random"))

fdi_region <- fdi |> arrange(year, dollar_value) |>
  group_by(year) |>
  mutate(rank = rank(-dollar_value, ties.method = "min")) |>
  mutate(position = rank(-dollar_value, ties.method = "random"))

first_year_cdi <- cdi_region$year |> min()
last_year_cdi <- cdi_region$year |> max()

first_year_fdi <- fdi_region$year |> min()
last_year_fdi <- fdi_region$year |> max()

first_year <- max(first_year_cdi, first_year_fdi)
last_year <- min(last_year_cdi, last_year_fdi)

first_year <- 2014
last_year <- 2023


#### cdi to region (ie fdi from Canada) ####

# filter for chosen years
cdi_region <- cdi_region |> 
  filter(year >= first_year & year <= last_year)

# bump plots require 2 or more data points for a country
# this filters out those with 1 or less
cdi_plotting <- cdi_region |>
  group_by(region) |>
  mutate(years=n())|>
  filter(years>1)

# misc. plot variables
label_padding = .2
font_size = '12px'
font_rank_size = '14px'

cdi_plot <- cdi_plotting |>
  ggplot() +
  # make bump plot
  ggbump::geom_bump(mapping=aes(x=year,y=position, group=region, colour = I(plot_colour))) +
  # add dots to bump plot
  geom_point(mapping=aes(x=year,y=position, group=region, colour = I(plot_colour))) +
  # rank from 1 down
  scale_y_reverse(limits = c(desired_max_rank, NA)) +
  # add labels for first year
  ggtext::geom_richtext(data = cdi_plotting|>filter(year==first_year), 
                        hjust=1,
                        mapping=aes(y=position, x=year-label_padding, 
                                    label.size=NA, family="sans",
                                    label=glue("<span style='font-size:{font_size};'>{region}<span style='color:white;'>...</span><span style='font-size:{font_rank_size};'>**{rank}**</span></span>")))+
  # add labels for last year
  ggtext::geom_richtext(data = cdi_plotting|>filter(year==last_year), 
                        hjust=0,family="sans",
                        mapping=aes(y=position, x=year+label_padding, 
                                    label.size=NA,
                                    label=glue("<span style='font-size:{font_size};'><span style='font-size:{font_rank_size};'>**{rank}**</span><span style='color:white;'>...</span>{region}</span>")))+
  #add breathing room in x axis to account for labels, change breaks to years
  scale_x_continuous(limits=c(first_year - 3.5, last_year + 3.5), 
                     breaks = seq(from = first_year, to = last_year, by = 1)) +
  theme_minimal()+
  theme(text=element_text(family="sans"), 
        plot.title = element_text(size=14, hjust = 0.5),
        axis.text.x=element_text(size=10, vjust=5),
        axis.ticks=element_blank(),
        axis.text.y=element_blank(),
        panel.background = element_blank(),
        panel.grid = element_blank()) +
  labs(title="Ranking of Canadian direct investment abroad by total net flows")+
  xlab("Year") +
  ylab("")

cdi_plot

# save image to port into decks etc., done this way to ensure standard ratios
ggsave("cdi_region_bump_plot.png", cdi_plot, bg = 'white', height = 8, width = 9.5, units = "in")





#### fdi to region (ie cdi from Canada) ####

# filter on chosen years
fdi_region <- fdi_region |> 
  filter(year >= first_year & year <= last_year)

# bump plots require 2 or more data points for a country
# this filters out those with 1 or less
fdi_plotting <- fdi_region |>
  group_by(region) |>
  mutate(years=n())|>
  filter(years>1)

# misc. plot variables
label_padding = .2
font_size = '12px'
font_rank_size = '14px'

fdi_plot <- fdi_plotting |>
  ggplot() +
  # make bump plot
  ggbump::geom_bump(mapping=aes(x=year,y=position, group=region, colour = I(plot_colour))) +
  # add dots to bump plot
  geom_point(mapping=aes(x=year,y=position, group=region, colour = I(plot_colour))) +
  # rank from 1 down
  scale_y_reverse(limits = c(desired_max_rank, NA)) +
  # add labels for first year
  ggtext::geom_richtext(data = fdi_plotting|>filter(year==first_year), 
                        hjust=1,
                        mapping=aes(y=position, x=year-label_padding, 
                                    label.size=NA, family="sans",
                                    label=glue("<span style='font-size:{font_size};'>{region}<span style='color:white;'>...</span><span style='font-size:{font_rank_size};'>**{rank}**</span></span>")))+
  # add labels for last year
  ggtext::geom_richtext(data = fdi_plotting|>filter(year==last_year), 
                        hjust=0,family="sans",
                        mapping=aes(y=position, x=year+label_padding, 
                                    label.size=NA,
                                    label=glue("<span style='font-size:{font_size};'><span style='font-size:{font_rank_size};'>**{rank}**</span><span style='color:white;'>...</span>{region}</span>")))+
  #add breathing room in x axis to account for labels, change breaks to years
  scale_x_continuous(limits=c(first_year - 3.5, last_year + 3.5), 
                     breaks = seq(from = first_year, to = last_year, by = 1)) +
  theme_minimal()+
  theme(text=element_text(family="sans"), 
        plot.title = element_text(size=14, hjust = 0.5),
        axis.text.x=element_text(size=10, vjust=5),
        axis.ticks=element_blank(),
        axis.text.y=element_blank(),
        panel.background = element_blank(),
        panel.grid = element_blank()) +
  labs(title="Ranking of foreign direct investment in Canada by total net flows")+
  xlab("Year") +
  ylab("")

fdi_plot


# save image to port into decks etc., done this way to ensure standard ratios
ggsave("fdi_region_bump_plot.png", fdi_plot, bg = 'white', height = 8, width = 9.5, units = "in")

