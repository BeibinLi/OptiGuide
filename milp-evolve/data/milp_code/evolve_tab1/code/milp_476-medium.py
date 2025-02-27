import random
import time
import numpy as np
import networkx as nx
from pyscipopt import Model, quicksum

class NMD:
    def __init__(self, parameters, seed=None):
        for key, value in parameters.items():
            setattr(self, key, value)
        self.seed = seed
        if self.seed:
            random.seed(seed)
            np.random.seed(seed)
    
    def generate_distribution_graph(self):
        n_nodes = np.random.randint(self.min_centers, self.max_centers)
        G = nx.erdos_renyi_graph(n=n_nodes, p=self.route_prob, directed=True, seed=self.seed)
        return G

    def generate_magazine_data(self, G):
        for node in G.nodes:
            G.nodes[node]['loads'] = np.random.randint(50, 500)
        for u, v in G.edges:
            G[u][v]['dist_time'] = np.random.randint(1, 5)
            G[u][v]['cap'] = np.random.randint(20, 100)

    def generate_incompatibility_data(self, G):
        E_invalid = set()
        for edge in G.edges:
            if np.random.random() <= self.exclusion_rate:
                E_invalid.add(edge)
        return E_invalid

    def create_centers(self, G):
        centers = list(nx.find_cliques(G.to_undirected()))
        return centers

    def get_instance(self):
        G = self.generate_distribution_graph()
        self.generate_magazine_data(G)
        E_invalid = self.generate_incompatibility_data(G)
        centers = self.create_centers(G)

        center_cap = {node: np.random.randint(100, 500) for node in G.nodes}
        dist_cost = {(u, v): np.random.uniform(10.0, 50.0) for u, v in G.edges}
        daily_distributions = [(center, np.random.uniform(500, 2000)) for center in centers]

        dist_scenarios = [{} for _ in range(self.no_of_scenarios)]
        for s in range(self.no_of_scenarios):
            dist_scenarios[s]['loads'] = {node: np.random.normal(G.nodes[node]['loads'], G.nodes[node]['loads'] * self.load_variation)
                                          for node in G.nodes}
            dist_scenarios[s]['dist_time'] = {(u, v): np.random.normal(G[u][v]['dist_time'], G[u][v]['dist_time'] * self.time_variation)
                                              for u, v in G.edges}
            dist_scenarios[s]['center_cap'] = {node: np.random.normal(center_cap[node], center_cap[node] * self.cap_variation)
                                               for node in G.nodes}
        
        financial_rewards = {node: np.random.uniform(50, 200) for node in G.nodes}
        travel_costs = {(u, v): np.random.uniform(5.0, 30.0) for u, v in G.edges}

        return {
            'G': G,
            'E_invalid': E_invalid,
            'centers': centers,
            'center_cap': center_cap,
            'dist_cost': dist_cost,
            'daily_distributions': daily_distributions,
            'piecewise_segments': self.piecewise_segments,
            'dist_scenarios': dist_scenarios,
            'financial_rewards': financial_rewards,
            'travel_costs': travel_costs,
        }

    def solve(self, instance):
        G, E_invalid, centers = instance['G'], instance['E_invalid'], instance['centers']
        center_cap = instance['center_cap']
        dist_cost = instance['dist_cost']
        daily_distributions = instance['daily_distributions']
        piecewise_segments = instance['piecewise_segments']
        dist_scenarios = instance['dist_scenarios']
        financial_rewards = instance['financial_rewards']
        travel_costs = instance['travel_costs']

        model = Model("NMD")
        
        # Define variables
        carrier_vars = {f"Carrier{node}": model.addVar(vtype="B", name=f"Carrier{node}") for node in G.nodes}
        route_vars = {f"Route_{u}_{v}": model.addVar(vtype="B", name=f"Route_{u}_{v}") for u, v in G.edges}
        dist_budget = model.addVar(vtype="C", name="dist_budget")
        daily_dist_vars = {i: model.addVar(vtype="B", name=f"Dist_{i}") for i in range(len(daily_distributions))}
        segment_vars = {(u, v): {segment: model.addVar(vtype="B", name=f"Segment_{u}_{v}_{segment}") for segment in range(1, piecewise_segments + 1)} for u, v in G.edges}
        
        # New variables for diverse constraints and objectives
        equipment_use_vars = {f"EquipUse{node}": model.addVar(vtype="B", name=f"EquipUse{node}") for node in G.nodes}
        header_vars = {f"Header{node}": model.addVar(vtype="I", name=f"Header{node}", lb=1, ub=5) for node in G.nodes}

        # Objective function
        objective_expr = quicksum(
            dist_scenarios[s]['loads'][node] * carrier_vars[f"Carrier{node}"]
            for s in range(self.no_of_scenarios) for node in G.nodes
        )
        objective_expr -= quicksum(
            quicksum(segment * segment_vars[(u,v)][segment] for segment in range(1, piecewise_segments + 1))
            for u, v in E_invalid
        )
        objective_expr -= quicksum(
            dist_cost[(u, v)] * route_vars[f"Route_{u}_{v}"]
            for u, v in G.edges
        )
        objective_expr += quicksum(price * daily_dist_vars[i] for i, (bundle, price) in enumerate(daily_distributions))
        objective_expr -= quicksum(equipment_use_vars[f"EquipUse{node}"] * 20 for node in G.nodes)
        objective_expr += quicksum(financial_rewards[node] * carrier_vars[f"Carrier{node}"] for node in G.nodes)
        objective_expr -= quicksum(travel_costs[(u, v)] * route_vars[f"Route_{u}_{v}"] for u, v in G.edges)
        
        # Constraints
        for i, center in enumerate(centers):
            model.addCons(
                quicksum(carrier_vars[f"Carrier{node}"] for node in center) <= 1,
                name=f"CarrierGroup_{i}"
            )

        for u, v in G.edges:
            model.addCons(
                carrier_vars[f"Carrier{u}"] + carrier_vars[f"Carrier{v}"] <= 1 + route_vars[f"Route_{u}_{v}"],
                name=f"Flow_{u}_{v}"
            )
            model.addCons(
                route_vars[f"Route_{u}_{v}"] == quicksum(segment_vars[(u, v)][segment] for segment in range(1, piecewise_segments + 1)),
                name=f"PiecewiseDist_{u}_{v}"
            )
            
        model.addCons(
            dist_budget <= self.dist_hours,
            name="DistTime_Limit"
        )

        # New Constraints to ensure balance and resource utilization
        for node in G.nodes:
            model.addCons(
                equipment_use_vars[f"EquipUse{node}"] <= carrier_vars[f"Carrier{node}"],
                name=f"EquipUseConstraint_{node}"
            )
            model.addCons(
                quicksum(segment_vars[(u, v)][segment] for u, v in G.edges if u == node or v == node for segment in range(1, piecewise_segments + 1)) <= header_vars[f"Header{node}"] * 20,
                name=f"HeaderConstraint_{node}"
            )
        
        model.setObjective(objective_expr, "maximize")

        start_time = time.time()
        model.optimize()
        end_time = time.time()
        
        return model.getStatus(), end_time - start_time

if __name__ == '__main__':
    seed = 42
    parameters = {
        'min_centers': 11,
        'max_centers': 900,
        'route_prob': 0.24,
        'exclusion_rate': 0.38,
        'dist_hours': 1575,
        'piecewise_segments': 60,
        'no_of_scenarios': 1260,
        'load_variation': 0.66,
        'time_variation': 0.66,
        'cap_variation': 0.38,
        'financial_param1': 555,
        'financial_param2': 2625,
        'dist_cost_param_1': 45.0,
        'move_capacity': 30.0,
    }

    nmd = NMD(parameters, seed=seed)
    instance = nmd.get_instance()
    solve_status, solve_time = nmd.solve(instance)
    print(f"Solve Status: {solve_status}")
    print(f"Solve Time: {solve_time:.2f} seconds")