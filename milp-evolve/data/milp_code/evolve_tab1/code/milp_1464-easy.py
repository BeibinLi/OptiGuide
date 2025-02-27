import random
import time
import numpy as np
from itertools import combinations
from pyscipopt import Model, quicksum
import networkx as nx
from scipy.stats import norm

class Graph:
    def __init__(self, number_of_nodes, edges, degrees, neighbors):
        self.number_of_nodes = number_of_nodes
        self.nodes = np.arange(number_of_nodes)
        self.edges = edges
        self.degrees = degrees
        self.neighbors = neighbors

    @staticmethod
    def barabasi_albert(number_of_nodes, affinity):
        assert affinity >= 1 and affinity < number_of_nodes

        edges = set()
        degrees = np.zeros(number_of_nodes, dtype=int)
        neighbors = {node: set() for node in range(number_of_nodes)}
        for new_node in range(affinity, number_of_nodes):
            if new_node == affinity:
                neighborhood = np.arange(new_node)
            else:
                neighbor_prob = degrees[:new_node] / (2 * len(edges))
                neighborhood = np.random.choice(new_node, affinity, replace=False, p=neighbor_prob)
            for node in neighborhood:
                edges.add((node, new_node))
                degrees[node] += 1
                degrees[new_node] += 1
                neighbors[node].add(new_node)
                neighbors[new_node].add(node)

        graph = Graph(number_of_nodes, edges, degrees, neighbors)
        return graph

class FleetManagement:
    def __init__(self, parameters, seed=None):
        for key, value in parameters.items():
            setattr(self, key, value)

        self.seed = seed
        if self.seed:
            random.seed(seed)
            np.random.seed(seed)

    def generate_instance(self):
        assert self.Number_of_Trucks > 0 and self.Number_of_Routes > 0
        assert self.Min_Truck_Cost >= 0 and self.Max_Truck_Cost >= self.Min_Truck_Cost
        assert self.Route_Cost_Lower_Bound >= 0 and self.Route_Cost_Upper_Bound >= self.Route_Cost_Lower_Bound
        assert self.Min_Truck_Capacity > 0 and self.Max_Truck_Capacity >= self.Min_Truck_Capacity

        truck_costs = np.random.randint(self.Min_Truck_Cost, self.Max_Truck_Cost + 1, self.Number_of_Trucks)
        route_costs = np.random.randint(self.Route_Cost_Lower_Bound, self.Route_Cost_Upper_Bound + 1, (self.Number_of_Trucks, self.Number_of_Routes))
        truck_capacities = np.random.randint(self.Min_Truck_Capacity, self.Max_Truck_Capacity + 1, self.Number_of_Trucks)
        route_demands_mean = np.ones(self.Number_of_Routes) * 5  # Mean demand
        route_demands_stddev = np.ones(self.Number_of_Routes) * 1.5  # Standard deviation of demand
        
        graph = Graph.barabasi_albert(self.Number_of_Trucks, self.Affinity)
        incompatibilities = set(graph.edges)
        
        # Data related to dynamic route dependency constraints
        set_A = [0, 1, 2]  # Example routes
        set_B = [3, 4]  # Dependent routes
        
        # Data related to exclusive truck use conditions
        exclusive_truck_pairs = [(0, 1), (2, 3)]
        exclusive_route_pairs = [(0, 1), (2, 3)]
        
        # New Data for Time Windows and Fuel Prices
        early_time_windows = np.random.randint(self.Min_Early_Time_Window, self.Max_Early_Time_Window, self.Number_of_Routes)
        late_time_windows = np.random.randint(self.Min_Late_Time_Window, self.Max_Late_Time_Window, self.Number_of_Routes)
        fuel_prices = np.random.uniform(self.Min_Fuel_Price, self.Max_Fuel_Price)
        
        # New Data for Spare Parts Inventory
        spare_parts_inventory = np.random.randint(self.Min_Spare_Part_Inventory, self.Max_Spare_Part_Inventory, self.Number_of_Spare_Parts)
        
        # New Data for Technician Skill Levels
        technician_skills = np.random.randint(self.Min_Technician_Skill, self.Max_Technician_Skill, (self.Number_of_Technicians, self.Number_of_Trucks))
        
        # New Data for Zoning Restrictions
        truck_zones = np.random.randint(1, self.Zoning_Options + 1, self.Number_of_Trucks)
        restricted_zones = self.Restricted_Zones
        
        return {
            "truck_costs": truck_costs,
            "route_costs": route_costs,
            "truck_capacities": truck_capacities,
            "route_demands_mean": route_demands_mean,
            "route_demands_stddev": route_demands_stddev,
            "graph": graph,
            "incompatibilities": incompatibilities,
            "set_A": set_A,
            "set_B": set_B,
            "exclusive_truck_pairs": exclusive_truck_pairs,
            "exclusive_route_pairs": exclusive_route_pairs,
            "early_time_windows": early_time_windows,
            "late_time_windows": late_time_windows,
            "fuel_prices": fuel_prices,
            "spare_parts_inventory": spare_parts_inventory,
            "technician_skills": technician_skills,
            "truck_zones": truck_zones,
            "restricted_zones": restricted_zones,
        }
        
    def solve(self, instance):
        truck_costs = instance['truck_costs']
        route_costs = instance['route_costs']
        truck_capacities = instance['truck_capacities']
        route_demands_mean = instance['route_demands_mean']
        route_demands_stddev = instance['route_demands_stddev']
        graph = instance['graph']
        incompatibilities = instance['incompatibilities']
        set_A = instance['set_A']
        set_B = instance['set_B']
        exclusive_truck_pairs = instance['exclusive_truck_pairs']
        exclusive_route_pairs = instance['exclusive_route_pairs']
        early_time_windows = instance['early_time_windows']
        late_time_windows = instance['late_time_windows']
        fuel_prices = instance['fuel_prices']
        spare_parts_inventory = instance['spare_parts_inventory']
        technician_skills = instance['technician_skills']
        truck_zones = instance['truck_zones']
        restricted_zones = instance['restricted_zones']
        
        model = Model("FleetManagement")
        number_of_trucks = len(truck_costs)
        number_of_routes = len(route_costs[0])
        number_of_spare_parts = len(spare_parts_inventory)
        number_of_technicians = technician_skills.shape[0]
        M = sum(truck_capacities)  # Big M
        
        # Decision variables
        truck_vars = {t: model.addVar(vtype="B", name="Truck_{}".format(t)) for t in range(number_of_trucks)}
        route_vars = {(t, r): model.addVar(vtype="B", name="Truck_{}_Route_{}".format(t, r)) for t in range(number_of_trucks) for r in range(number_of_routes)}
        delivery_time_vars = {r: model.addVar(vtype="C", name="Delivery_Time_{}".format(r)) for r in range(number_of_routes)}
        
        # New Variables for Spare Parts
        spare_parts_vars = {(t, p): model.addVar(vtype="B", name="Truck_{}_SparePart_{}".format(t, p)) for t in range(number_of_trucks) for p in range(number_of_spare_parts)}
        spare_parts_amount_vars = {(t, p): model.addVar(vtype="C", name="Amount_Truck_{}_SparePart_{}".format(t, p)) for t in range(number_of_trucks) for p in range(number_of_spare_parts)}
        
        # New Variables for Technician Assignments
        technician_vars = {(tech, t): model.addVar(vtype="B", name="Technician_{}_Truck_{}".format(tech, t)) for tech in range(number_of_technicians) for t in range(number_of_trucks)}
        
        # New Variables for Zoning
        zone_vars = {t: model.addVar(vtype="I", name="Truck_{}_Zone".format(t), lb=1) for t in range(number_of_trucks)}

        # Objective: minimize the total cost including truck startup costs, route service costs, penalties for unavailability, and overtime costs
        model.setObjective(
            quicksum(truck_costs[t] * truck_vars[t] for t in range(number_of_trucks)) +
            quicksum(route_costs[t, r] * route_vars[t, r] * fuel_prices for t in range(number_of_trucks) for r in range(number_of_routes)), 
            "minimize"
        )
        
        # Constraints: Each route must be served by exactly one truck
        for r in range(number_of_routes):
            model.addCons(quicksum(route_vars[t, r] for t in range(number_of_trucks)) == 1, "Route_{}_Demand".format(r))
        
        # Constraints: Only active trucks can serve routes
        for t in range(number_of_trucks):
            for r in range(number_of_routes):
                model.addCons(route_vars[t, r] <= truck_vars[t], "Truck_{}_Serve_{}".format(t, r))

        # Constraints: Trucks cannot exceed their capacity using Big M (Robust constraint)
        delta = 0.1  # Uncertainty level
        for t in range(number_of_trucks):
            capacity_ub = truck_capacities[t] * (1 + delta)  # Upper bound considering uncertainty
            model.addCons(quicksum(route_demands_mean[r] * route_vars[t, r] for r in range(number_of_routes)) <= capacity_ub * truck_vars[t], "Truck_{}_Capacity".format(t))

        # Constraints: Satisfying route demands with a specified probability (Stochastic constraint)
        alpha = 0.95  # Confidence level
        z_score = norm.ppf(alpha)
        for r in range(number_of_routes):
            mean_demand = route_demands_mean[r]
            stddev_demand = route_demands_stddev[r]
            demand_with_uncertainty = mean_demand + z_score * stddev_demand  # Adjusted demand for the given confidence level
            model.addCons(quicksum(route_vars[t, r] for t in range(number_of_trucks)) * demand_with_uncertainty <= quicksum(truck_capacities[t] * truck_vars[t] for t in range(number_of_trucks)), "Route_{}_Stochastic_Demand".format(r))

        # Constraints: Truck Graph Incompatibilities
        for count, (i, j) in enumerate(incompatibilities):
            model.addCons(truck_vars[i] + truck_vars[j] <= 1, "Incompatibility_{}".format(count))

        # Dynamic Route Dependency Constraints
        for r_a in set_A:
            for r_b in set_B:
                model.addCons(quicksum(route_vars[t, r_a] for t in range(number_of_trucks)) <= quicksum(route_vars[t, r_b] for t in range(number_of_trucks)), "RouteDep_{}_{}".format(r_a, r_b))

        # Exclusive Truck Use Constraints
        for (i, j), (r1, r2) in zip(exclusive_truck_pairs, exclusive_route_pairs):
            for t in range(number_of_trucks):
                model.addCons(truck_vars[i] <= 1 - route_vars[i, r1], "Exclusive_{}_{}".format(i, r1))
                model.addCons(truck_vars[j] <= 1 - route_vars[j, r2], "Exclusive_{}_{}".format(j, r2))

        # Time Windows Constraints
        for r in range(number_of_routes):
            model.addCons(delivery_time_vars[r] >= early_time_windows[r], "Early_Time_Window_{}".format(r))
            model.addCons(delivery_time_vars[r] <= late_time_windows[r], "Late_Time_Window_{}".format(r))

        # Constraints: Spare Parts Inventory
        for t in range(number_of_trucks):
            for p in range(number_of_spare_parts):
                model.addCons(spare_parts_amount_vars[t, p] <= M * spare_parts_vars[t, p], "SparePart_Usage_{}_{}".format(t, p))
                model.addCons(spare_parts_amount_vars[t, p] <= spare_parts_inventory[p], "SparePart_Limit_{}_{}".format(t, p))

        # Constraints: Technician Skill Levels
        for tech in range(number_of_technicians):
            for t in range(number_of_trucks):
                model.addCons(technician_vars[tech, t] <= technician_skills[tech, t], "Technician_Skill_{}_{}".format(tech, t))

        # Constraints: Zoning Restrictions
        for t in range(number_of_trucks):
            model.addCons(zone_vars[t] == truck_zones[t], "Truck_Zone_{}".format(t))
            
        for t in range(number_of_trucks):
            model.addCons(zone_vars[t] <= self.Zoning_Options, "Zone_Options_{}".format(t))
            
        for z in restricted_zones:
            model.addCons(quicksum(route_vars[t, r] for t in range(number_of_trucks) for r in range(number_of_routes) if truck_zones[t] == z) == 0, "Restricted_Zone_{}".format(z))

        start_time = time.time()
        model.optimize()
        end_time = time.time()
        
        return model.getStatus(), end_time - start_time, model.getObjVal()

if __name__ == '__main__':
    seed = 42
    parameters = {
        'Number_of_Trucks': 40,
        'Number_of_Routes': 154,
        'Route_Cost_Lower_Bound': 1200,
        'Route_Cost_Upper_Bound': 3000,
        'Min_Truck_Cost': 1800,
        'Max_Truck_Cost': 5000,
        'Min_Truck_Capacity': 1440,
        'Max_Truck_Capacity': 2000,
        'Affinity': 4,
        'Min_Early_Time_Window': 5,
        'Max_Early_Time_Window': 10,
        'Min_Late_Time_Window': 15,
        'Max_Late_Time_Window': 20,
        'Min_Fuel_Price': 1.0,
        'Max_Fuel_Price': 3.0,
        'Min_Spare_Part_Inventory': 10,
        'Max_Spare_Part_Inventory': 100,
        'Number_of_Spare_Parts': 5,
        'Min_Technician_Skill': 1,
        'Max_Technician_Skill': 10,
        'Number_of_Technicians': 10,
        'Zoning_Options': 5,
        'Restricted_Zones': [1, 3],
    }
    fleet_management_optimizer = FleetManagement(parameters, seed)
    instance = fleet_management_optimizer.generate_instance()
    solve_status, solve_time, objective_value = fleet_management_optimizer.solve(instance)

    print(f"Solve Status: {solve_status}")
    print(f"Solve Time: {solve_time:.2f} seconds")
    print(f"Objective Value: {objective_value:.2f}")