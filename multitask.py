import numpy as np
from gridworld import *
from mdp_solver import *
import math
import random
import scipy
from scipy.stats import chi2
from mdp_solver import value_iteration_to_policy

class MdpClass(object):
    def __init__(self, class_id, weights_mean, weights_cov):
        self.class_id = class_id
        self.weights_mean = weights_mean
        self.weights_cov = weights_cov
        self.inv_weights_cov = np.linalg.inv(weights_cov)

    def likelihood(self, weights):
        # Note: we ignore the 1./math.sqrt((2.*math.pi)**self.weights_cov.shape[0]) constant
        multiplier = math.pow(np.linalg.det(self.weights_cov), -0.5)
        exponent = -0.5 * np.dot(np.dot(np.transpose(weights - self.weights_mean), self.inv_weights_cov), weights - self.weights_mean)
        if multiplier < 0 or math.exp(exponent) < 0:
            print 'Mean: {0} Cov: {1}'.format(self.weights_mean, self.weights_cov)
            print 'Weights: {0}'.format(weights)
            print 'Multiplier: {0} Exponent: {1}'.format(multiplier, exponent)
            raise Exception('Multiplier or Exponent < 0 in multivariate normal likelihood function.')
        return multiplier * math.exp(exponent)

    def sample(self):
        return np.random.multivariate_normal(self.weights_mean, self.weights_cov)

    def posterior(self, states, rewards):
        """
        We have the product of two Gaussians, so we can derive a closed form update for the posterior.
        """
        y = self.inv_weights_cov + np.dot(np.transpose(states), states)
        post_cov = np.linalg.inv(y)
        post_mean = np.dot(np.linalg.inv(y), np.dot(self.inv_weights_cov, self.weights_mean) + np.dot(np.transpose(states), rewards))
        return MdpClass(self.class_id, post_mean, post_cov)

    def sample_posterior(self, states, rewards):
        return self.posterior(states, rewards).sample()

class NormalInverseWishartDistribution(object):
    def __init__(self, mu, lmbda, nu, psi):
        assert(nu > psi.shape[0]+1)
        self.mu = mu
        self.lmbda = float(lmbda)
        self.nu = nu
        self.psi = psi
        self.inv_psi = np.linalg.inv(psi)
        self.cholesky = np.linalg.cholesky(self.inv_psi)
        self.norm = None
        self.log_norm = None

    def get_norm(self):
        """
        Returns the normalising constant of the distribution.
        TODO: Check for underflow here. May need to do log-likelihood, in which case, scipy
        provides an implementation already.
        """
        if self.norm is None:
            d = self.psi.shape[0]
            self.norm  = math.pow(2.0,-0.5*self.nu*d)
            self.norm *= math.pow(np.linalg.det(self.psi),-0.5*self.nu)
            # Self-made multivariate gamma: http://en.wikipedia.org/wiki/Multivariate_gamma_function
            self.norm *= math.pow(math.pi,-0.25*d*(d-1))
            for i in xrange(d):
                self.norm /= scipy.special.gamma((self.nu + 1 - i) * 0.5)
        return self.norm

    def get_log_norm(self):
        """
        Returns the log of the normalising constant of the distribution.
        """
        if self.log_norm is None:
            d = self.psi.shape[0]
            self.log_norm  = math.log(2.0) * (-0.5*self.nu*d)
            self.log_norm += math.log(np.linalg.det(self.psi)) * (-0.5*self.nu)
            # Self-made multivariate gamma: http://en.wikipedia.org/wiki/Multivariate_gamma_function
            self.log_norm += math.log(math.pi) * (-0.25*d*(d-1))
            for i in xrange(d):
                self.log_norm -= math.log(scipy.special.gamma((self.nu + 1 - i) * 0.5))
        return self.log_norm


    def likelihood(self, mean, cov):
        """
        Returns the likelihood of the mean and covariance matrices being generated by this NIW.
        Note that likelihood is probably going to underflow in practice.
        """
        # First calculate the likelihood for the normal
        normal_cov = cov / self.lmbda
        # Ignoring 1./math.sqrt((2.*math.pi)**k) constant
        multiplier = math.pow(np.linalg.det(normal_cov),-0.5)
        exponent = -0.5 * np.dot(np.dot(np.transpose(mean - self.mu), normal_cov), mean - self.mu)
        normal_likelihood = multiplier * math.exp(exponent)
        # Now calculate the likelihood for the inverse wishart
        norm = self.get_norm()
        d = self.psi.shape[0]
        print 'det: {0} log: {1}'.format(np.linalg.det(cov), math.log(np.linalg.det(cov)))
        print 'det exp: {0}'.format(-0.5*(self.nu + d + 1))
        inv_wishart_likelihood  = math.pow(np.linalg.det(cov),-0.5*(self.nu + d + 1))
        inv_wishart_likelihood *= math.exp(-0.5 * np.trace(np.dot(self.psi, np.linalg.inv(cov))))
        inv_wishart_likelihood *= norm
        return normal_likelihood * inv_wishart_likelihood

    def log_likelihood(self, mean, cov):
        """
        Returns the log-likelihood of the mean and covariance matrices being generated by this NIW.
        """
        # First calculate the likelihood for the normal
        normal_cov = cov / self.lmbda
        # Ignoring 1./math.sqrt((2.*math.pi)**k) constant
        multiplier = -0.5 * math.log(np.linalg.det(normal_cov))
        exponent = -0.5 * np.dot(np.dot(np.transpose(mean - self.mu), normal_cov), mean - self.mu)
        normal_likelihood = multiplier + exponent
        # Now calculate the likelihood for the inverse wishart
        log_norm = self.get_log_norm()
        d = self.psi.shape[0]
        inv_wishart_likelihood  = math.log(np.linalg.det(cov)) * (-0.5*(self.nu + d + 1))
        inv_wishart_likelihood += -0.5 * np.trace(np.dot(self.psi, np.linalg.inv(cov)))
        inv_wishart_likelihood += log_norm
        return normal_likelihood + inv_wishart_likelihood

    def sample(self):
        sigma = np.linalg.inv(self.wishartrand())
        return (np.random.multivariate_normal(self.mu, sigma / float(self.lmbda)), sigma)

    def wishartrand(self):
        dim = self.inv_psi.shape[0]
        foo = np.zeros((dim,dim))

        for i in range(dim):
            for j in range(i+1):
                if i == j:
                    foo[i,j] = np.sqrt(chi2.rvs(self.nu-(i+1)+1))
                else:
                    foo[i,j]  = np.random.normal(0,1)
        return np.dot(self.cholesky, np.dot(foo, np.dot(foo.T, self.cholesky.T)))

    def posterior(self, data):
        n = len(data)
        if n == 0:
            return NormalInverseWishartDistribution(self.mu, self.lmbda, self.nu, self.psi)
        mean_data = np.mean(data, axis=0)
        sum_squares = np.sum([np.array(np.matrix(x - mean_data).T * np.matrix(x - mean_data)) for x in data], axis=0)
        assert(sum_squares.shape == (self.mu.shape[0], self.mu.shape[0]))
        mu_n = (self.lmbda * self.mu + n * mean_data) / (self.lmbda + n)
        lmbda_n = self.lmbda + n
        nu_n = self.nu + n
        psi_n = self.psi + sum_squares + self.lmbda * n / float(self.lmbda + n) * np.array(np.matrix(mean_data - self.mu).T * np.matrix(mean_data - self.mu))
        return NormalInverseWishartDistribution(mu_n, lmbda_n, nu_n, psi_n)

    def sample_posterior(self, data):
        return self.posterior(data).sample()

def proportional_selection(proportions, partition=None):
    if partition is None:
        partition = sum(proportions)
    if partition <= 0.:
        #print 'WARNING: Partition == 0. Using default equal proportion.'.format(proportions)
        proportions = [1. / len(proportions) for x in proportions]
    else:
        proportions = [x / partition for x in proportions]
    u = random.random()
    cur = 0.
    for i,prob in enumerate(proportions):
        cur += prob
        if u <= cur:
            return i

class LinearGaussianRewardModel(object):
    """
    A model of the rewards for experiment 1 in the Wilson et al. paper. See section 4.4 for implementation details.
    """
    def __init__(self, num_colors, reward_stdev, classes, assignments, auxillary_distribution, alpha=0.5, m=2, burn_in=100, mcmc_samples=500, thin=1):
        self.weights_size = num_colors * NUM_RELATIVE_CELLS
        self.reward_stdev = reward_stdev
        self.classes = classes
        self.assignments = assignments
        self.total_mpds = sum(assignments) + 1
        self.auxillary_distribution = auxillary_distribution
        self.alpha = alpha
        self.m = m
        self.burn_in = burn_in
        self.mcmc_samples = mcmc_samples
        self.thin = thin
        assert(len(classes) == len(assignments))
        self.states = []
        self.rewards = []
        self.auxillaries = [self.sample_auxillary(len(self.classes) + i) for i in range(self.m)]
        c = proportional_selection(self.assignments + [self.alpha / self.m for _ in self.auxillaries])
        self.map_class = (self.classes + self.auxillaries)[c]
        self.weights = self.map_class.sample()
        

    def add_observation(self, state, reward):
        self.states.append(state)
        self.rewards.append(reward)

    def update_beliefs(self):
        """
        Implements the efficient approximation of Algorithm 2 from Wilson et al.
        described in section 4.4. to update the model parameters during an episode.
        TODO: Should we be adding auxillary classes inside the MCMC loop?
        """
        states = np.array(self.states)
        rewards = np.array(self.rewards)
        samples = np.zeros(len(self.classes)+self.m)
        c = proportional_selection(self.assignments + [self.alpha / self.m for _ in self.auxillaries])
        mdp_class = (self.classes + self.auxillaries)[c]
        w = mdp_class.sample_posterior(states, rewards)
        max_likelihood = None
        for i in range(self.mcmc_samples):
            self.auxillaries = [self.sample_auxillary(len(self.classes) + j) for j in range(self.m)]
            mdp_class = self.sample_assignment(states, rewards, w)
            w = mdp_class.sample_posterior(states, rewards)
            if mdp_class.class_id >= len(self.classes):
                log_likelihood = self.alpha / float(self.m)
            else:
                log_likelihood = self.assignments[mdp_class.class_id]
            log_likelihood += mdp_class.posterior(states, rewards).likelihood(w)
            if i >= self.burn_in and i % self.thin == 0:
                samples[mdp_class.class_id] += 1
                if max_likelihood is None or log_likelihood > max_likelihood:
                    max_likelihood = log_likelihood
                    map_c = mdp_class
                    map_w = w
        extra = ''
        if c != map_c.class_id:
            extra = '--- SWITCHED'
        print 'Step {2}: Assignment Distribution: {0} Original: {1}->{3} {4}'.format(samples, c, len(self.states), map_c.class_id, extra)
        '''
        # MAP calculations
        map_c = np.argmax(samples)
        print 'Step {2}: Assignment Distribution: {0} Original: {1}->{3} {4}'.format(samples, c, len(self.states), map_c, extra)
        if map_c >= len(self.classes):
            # We are keeping this auxillary class
            new_class = self.auxillaries[map_c - len(self.classes)]
            new_class.class_id = len(self.classes)
            self.map_class = new_class
            self.weights = self.sample_weights(states, rewards)
            # None of the other auxillary classes were good enough -- resample them
            self.auxillaries = [new_class] + [self.sample_auxillary(len(self.classes) + i + 1) for i in range(self.m - 1)]
        else:
            self.map_class = self.classes[map_c]
            self.weights = self.sample_weights(states, rewards)
            # None of the auxillary classes were good enough -- resample them
            self.auxillaries = [self.sample_auxillary(len(self.classes) + i) for i in range(self.m)]
        '''
        # Different MAP calculations
        self.map_class = map_c
        self.weights = map_w

    def sample_assignment(self, states, rewards, weights):
        """
        Implements Algorithm 3 from the Wilson et al. paper.
        """
        classes = [c for c in self.classes] # duplicate classes
        # Calculate likelihood of assigning to a known class
        assignment_probs = [self.assignments[i] * self.classes[i].posterior(states, rewards).likelihood(weights) for i in range(len(self.classes))]
        # Calculate likelihood of assigning to a new, unknown class with the default prior
        for i,aux in enumerate(self.auxillaries):
            assignment_probs.append(self.alpha / float(self.m) * aux.posterior(states, rewards).likelihood(weights))
            classes.append(aux) # add auxillary classes to the list of options
        # Sample an assignment proportional to the likelihoods
        return classes[proportional_selection(assignment_probs)]

    def sample_auxillary(self, class_id):
        (mean, cov) = self.auxillary_distribution.sample()
        return MdpClass(class_id, mean, cov)

    def sample_weights(self, states, rewards):
        return self.map_class.sample_posterior(states, rewards)


class MultiTaskBayesianAgent(Agent):
    """
    A Bayesian RL agent that infers a hierarchy of MDP distributions, with a top-level
    class distribution which parameterizes each bottom-level MDP distribution.

    TODO: Currently the agent assumes all MDPs are observed sequentially. Extending the
    algorithm to handle multiple, simultaneous MDPs may require non-trivial changes.
    """
    def __init__(self, width, height, num_colors, num_domains, reward_stdev, name=None, steps_per_policy=10, num_auxillaries=2, alpha=0.5, goal_known=True, burn_in=100, mcmc_samples=500, thin=1):
        super(MultiTaskBayesianAgent, self).__init__(width, height, num_colors, num_domains, name)
        self.reward_stdev = reward_stdev
        self.steps_per_policy = steps_per_policy
        self.num_auxillaries = num_auxillaries
        self.alpha = alpha
        self.goal_known = goal_known
        self.burn_in = burn_in
        self.mcmc_samples = mcmc_samples
        self.thin = thin
        self.state_size = num_colors * NUM_RELATIVE_CELLS
        self.auxillary_distribution = NormalInverseWishartDistribution(np.zeros(self.state_size), 0.1, self.state_size+2, np.identity(self.state_size))
        self.classes = []
        self.assignments = []
        self.weights = []
        self.model = LinearGaussianRewardModel(num_colors, self.reward_stdev, self.classes, self.assignments, self.auxillary_distribution, alpha=alpha, m=num_auxillaries)
        self.cur_mdp = 0
        self.steps_since_update = 0
        self.states = [[] for _ in range(num_domains)]
        self.rewards = [[] for _ in range(num_domains)]
        self.policy = None

    def episode_starting(self, idx, location, state):
        super(MultiTaskBayesianAgent, self).episode_starting(idx, location, state)
        if idx is not self.cur_mdp:
            self.update_beliefs()
            self.cur_mdp = idx
            self.update_policy()
            self.steps_since_update = 0
        self.prev_reward = None

    def episode_over(self, idx):
        assert(idx == self.cur_mdp)
        super(MultiTaskBayesianAgent, self).episode_over(idx)
        # TODO: Handle unknown goal locations

    def get_action(self, idx):
        assert(idx == self.cur_mdp)
        if self.steps_since_update >= self.steps_per_policy:
            self.update_policy()
            self.steps_since_update = 0
        self.steps_since_update += 1
        if self.policy is None:
            return random.choice([UP, DOWN, LEFT, RIGHT])
        return self.policy[self.location[idx]]

    def set_state(self, idx, location, state):
        assert(idx == self.cur_mdp)
        super(MultiTaskBayesianAgent, self).set_state(idx, location, state)
        if self.prev_reward is not None:
            self.model.add_observation(state, self.prev_reward)
            self.states[idx].append(state)
        #print 'STATE: {0} LOCATION: {1}'.format(state, location)

    def observe_reward(self, idx, r):
        assert(idx == self.cur_mdp)
        super(MultiTaskBayesianAgent, self).observe_reward(idx, r)
        self.prev_reward = r
        self.rewards[idx].append(r)

    def update_beliefs(self):
        """
        Implements Algorithm 2 from Wilson et al. to update the beliefs
        over all MDPs.

        Note that the beliefs of past MDPs are only updated between MDPs,
        for efficiency. See section 4.4 for details on the efficiency issue.
        """
        states = np.array(self.states)
        rewards = np.array(self.rewards)
        self.classes = [self.sample_auxillary(0)] # initial class
        self.assignments = [0 for _ in range(self.cur_mdp+1)] # initial assignments (all to initial class)
        self.weights = [self.classes[a].posterior(states[i], rewards[i]).sample() for i,a in enumerate(self.assignments)] # initial weights
        self.assignment_counts = [len(self.assignments)]
        max_likelihood = None
        samples = []
        for iteration in range(self.mcmc_samples):
            log_likelihood = 0
            aux_boundary = len(self.classes)
            # Add auxillary classes
            self.classes += [self.sample_auxillary(len(self.classes) + k) for k in range(self.num_auxillaries)]
            self.assignment_counts += [0] * self.num_auxillaries
            # Sample class assignments
            for j,a in enumerate([x for x in self.assignments]):
                # Remove the current mdp from the counts
                self.assignment_counts[a] -= 1
                # Calculate likelihood of assigning to each class
                assignment_probs = [self.assignment_counts[i] * self.classes[i].posterior(states[j], rewards[j]).likelihood(self.weights[j]) for i in range(len(self.classes) - self.num_auxillaries)]
                assignment_probs += [self.alpha / float(self.num_auxillaries) * self.classes[i].posterior(states[j], rewards[j]).likelihood(self.weights[j]) for i in range(len(self.classes) - self.num_auxillaries, len(self.classes))]
                z = sum(assignment_probs)
                # Sample an assignment proportional to the likelihoods
                chosen = self.classes[proportional_selection(assignment_probs, partition=z)]
                # Multiply the likelihood of sampling all the parameters for MAP calculation at the end of sampling.
                # Note: using log-likelihood to prevent underflows
                if z <= 0. or assignment_probs[chosen.class_id] <= 0.:
                    log_likelihood += math.log(1.0 / float(len(assignment_probs)))
                else:
                    log_likelihood += math.log(assignment_probs[chosen.class_id] / z)
                self.assignments[j] = chosen.class_id
                self.assignment_counts[chosen.class_id] += 1
            # Remove all classes with zero MDPs, doing some bookkeeping to adjust class IDs.
            updated_classes = []
            updated_assignments = [None for _ in self.assignments]
            updated_counts = []
            next_id = 0
            for j in range(len(self.classes)):
                if self.assignment_counts[j] > 0:
                    for k,a in enumerate(self.assignments):
                        if a == j:
                            updated_assignments[k] = next_id
                    updated_counts.append(self.assignment_counts[j])
                    self.classes[j].class_id = next_id
                    updated_classes.append(self.classes[j])
                    next_id += 1
            self.classes = updated_classes
            self.assignments = updated_assignments
            self.assignment_counts = updated_counts
            # Sample weights
            class_priors = [self.classes[a] for j,a in enumerate(self.assignments)]
            class_posteriors = [self.classes[a].posterior(states[j], rewards[j]) for j,a in enumerate(self.assignments)]
            self.weights = [c.sample() for c in class_posteriors]
            # Multiply in the probability of selecting those weights
            #log_likelihood += sum([math.log(c.likelihood(w)) for c,w in zip(class_posteriors, self.weights)])
            #print 'Weight LLs: {0}'.format([c.likelihood(w) for c,w in zip(class_priors, self.weights)])
            log_likelihood += sum([math.log(max(c.likelihood(w),1e-300)) for c,w in zip(class_priors, self.weights)])
            partial_log_likelihood = log_likelihood
            # Sample class parameters
            weight_clusters = [[]] * len(self.classes)
            for widx,a in enumerate(self.assignments):
                weight_clusters[a].append(self.weights[widx])
            for c,w in enumerate(weight_clusters):
                # Calculate the posterior distribution, given the weights assigned to this cluster
                cluster_posterior = self.auxillary_distribution.posterior(w)
                # Sample a cluster
                (mu,sigma) = cluster_posterior.sample()
                # Create the class from the sampled cluster parameters
                self.classes[c] = MdpClass(c, mu, sigma)
                # Multiply in the probability of selecting those cluster parameters
                log_likelihood += cluster_posterior.log_likelihood(mu,sigma)
            # Record samples
            if iteration >= self.burn_in and iteration % self.thin == 0:
                '''
                print 'Class weights: {0}'.format([[round(w,2) for w in c.weights_mean] for c in self.classes])
                print 'Class cov: {0}'.format([[round(w,2) for w in c.weights_cov.diagonal()] for c in self.classes])
                print 'Assignments: {0}'.format(self.assignments)
                print 'Posterior weights: {0}'.format([[round(w,2) for w in c.weights_mean] for c in class_posteriors])
                print 'Posterior cov: {0}'.format([[round(w,2) for w in c.weights_cov.diagonal()] for c in class_posteriors])
                print 'State shape: {0}'.format(states.shape)
                print 'Reward shape: {0}'.format(rewards.shape)
                print 'Log-likelihood: {0}'.format(log_likelihood)
                print ''
                print ''
                '''
                # TODO: import deepcopy for speed (meh, it's all sooo slow anyway)
                classes_copy = [x for x in self.classes]
                assignments_copy = [x for x in self.assignments]
                counts_copy = [x for x in self.assignment_counts]
                weights_copy = [x for x in self.weights]
                samples.append([classes_copy, assignments_copy, counts_copy, weights_copy, log_likelihood])
                if max_likelihood is None or log_likelihood > max_likelihood:
                    map_sample = samples[-1]
                    max_likelihood = log_likelihood
                    max_partial_likelihood = partial_log_likelihood
        # Proceed with the MAP parameters
        self.classes = map_sample[0]
        self.assignments = map_sample[1]
        self.assignment_counts = map_sample[2]
        self.weights = map_sample[3]
        print 'MAP Distribution: {0} (log-likelihood: {1}) Partial: {2}'.format(self.assignment_counts, max_likelihood, max_partial_likelihood)
        print 'MAP Assignments: {0}'.format(self.assignments)
        print 'Class Weight Means: {0}'.format([[round(w, 2) for w in c.weights_mean] for c in self.classes])
        print 'Class Weight Cov: {0}'.format([[round(w, 2) for w in c.weights_cov.diagonal()] for c in self.classes])
        self.model = LinearGaussianRewardModel(self.colors, self.reward_stdev, self.classes, self.assignment_counts, self.auxillary_distribution.posterior(self.weights), alpha=self.alpha, m=self.num_auxillaries)

    def update_policy(self):
        """
        Algorithm 1, Line 5 from Wilson et al.
        """
        self.model.update_beliefs()
        weights = self.model.weights
        if weights is None:
            return
        # Calculate the mean value of every cell, given the model weights
        cell_values = np.zeros((self.width, self.height))
        for x in range(self.width):
            for y in range(self.height):
                cell_values[x,y] = min(0, np.dot(weights, self.domains[self.cur_mdp].cell_states[x,y]))
        # TODO: Handle unknown goal locations by enabling passing a belief distribution over goal locations
        self.policy = value_iteration_to_policy(self.width, self.height, self.domains[self.cur_mdp].goal, cell_values)

    def sample_auxillary(self, class_id):
        (mean, cov) = self.auxillary_distribution.posterior(self.weights).sample()
        return MdpClass(class_id, mean, cov)

    def clear_memory(self, idx):
        super(MultiTaskBayesianAgent, self).clear_memory(idx)
        if self.cur_mdp is idx:
            self.cur_mdp -= 1
            self.policy = None
        self.states[idx] = []
        self.rewards[idx] = []

if __name__ == "__main__":
    TRUE_CLASS = 0
    SAMPLE_SIZE = 1000
    COLORS = 2
    RSTDEV = 0.3
    SIZE = COLORS * NUM_RELATIVE_CELLS
    NUM_DISTRIBUTIONS = 4

    niw_true = NormalInverseWishartDistribution(np.zeros(SIZE) - 3., 1., SIZE+2, np.identity(SIZE))
    true_params = [niw_true.sample() for _ in range(NUM_DISTRIBUTIONS)]
    classes = [MdpClass(i, mean, cov) for i,(mean,cov) in enumerate(true_params)]
    assignments = [1. for _ in classes]
    auxillary = NormalInverseWishartDistribution(np.zeros(SIZE) - 3., 1., SIZE+2, np.identity(SIZE))

    candidate_params = [auxillary.sample() for _ in range(NUM_DISTRIBUTIONS)]
    candidate_classes = [MdpClass(i, mean, cov) for i,(mean,cov) in enumerate(candidate_params)]
    model = LinearGaussianRewardModel(COLORS, RSTDEV, classes, assignments, auxillary)

    weights = classes[TRUE_CLASS].sample()

    print 'True class: {0}'.format(TRUE_CLASS)

    for s in range(SAMPLE_SIZE):
        q_sample = np.zeros((COLORS * NUM_RELATIVE_CELLS))
        for row in range(NUM_RELATIVE_CELLS):
            q_sample[row * COLORS + random.randrange(COLORS)] = 1
        r_sample = np.random.normal(loc=np.dot(weights, q_sample), scale=RSTDEV)
        model.add_observation(q_sample, r_sample)
        model.update_beliefs()
        print 'Samples: {0} Class belief: {1}'.format(s+1, model.map_class.class_id)